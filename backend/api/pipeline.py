"""
Pipeline convenience endpoints.
POST /api/pipeline/schema/{file_id}  — suggest + auto-confirm schema (LLM for low-confidence cols)
POST /api/pipeline/{period_id}       — extract → process → generate statements in one call
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import (
    get_db, File as FileModel, RawRecord, ColumnMapping,
    BusinessRecord, ValidationResult, ImportanceScore,
    JournalEntry, JournalLine, FinancialStatement, StatementLine, Period
)
from backend.services.schema_mapper import (
    map_columns_rule_based, map_columns_with_llm, merge_mappings
)
from backend.services.record_extractor import extract_records
from backend.services.validation_engine import validate_records, summarize_validations
from backend.services.importance_scorer import score_all_records
from backend.services.accounting_mapper import map_all_records
from backend.services.statement_generator import generate_income_statement, generate_trial_balance

router = APIRouter()


@router.post("/schema/{file_id}")
def pipeline_schema(file_id: int, db: Session = Depends(get_db)):
    """
    Step 1 of the pipeline: suggest column mappings using LLM for
    low-confidence columns, then auto-confirm all mappings.
    """
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")

    sample = db.query(RawRecord).filter(RawRecord.file_id == file_id).limit(5).all()
    if not sample:
        raise HTTPException(400, "No raw records found. Upload file first.")

    columns = list(sample[0].raw_data.keys())
    sample_rows = [r.raw_data for r in sample]

    # Rule-based pass
    rule_mappings = map_columns_rule_based(f.file_type, columns)

    # LLM for columns where rule-based confidence < 0.70
    low_conf_cols = [m["raw_column"] for m in rule_mappings if m["confidence"] < 0.70]
    llm_mappings = []
    if low_conf_cols:
        try:
            llm_mappings = map_columns_with_llm(f.file_type, low_conf_cols, sample_rows)
        except Exception:
            pass  # Degrade gracefully: keep rule-based if LLM unavailable

    final = merge_mappings(rule_mappings, llm_mappings)

    # Auto-confirm all mappings
    db.query(ColumnMapping).filter(ColumnMapping.file_id == file_id).delete()
    for m in final:
        cm = ColumnMapping(
            file_id=file_id,
            raw_column=m["raw_column"],
            standard_field=m["standard_field"],
            confidence=m["confidence"],
            approved=1,  # Auto-confirmed
        )
        db.add(cm)
    db.commit()

    return {
        "file_id": file_id,
        "file_type": f.file_type,
        "mappings_confirmed": len(final),
        "llm_cols_resolved": len(llm_mappings),
    }


@router.post("/{period_id}")
def run_pipeline(period_id: int, db: Session = Depends(get_db)):
    """
    Full pipeline for a period:
    1. Extract business records from all files with confirmed mappings
    2. Validate + score + create journal entries
    3. Generate income statement
    Returns a comprehensive result dict.
    """
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    if not files:
        raise HTTPException(404, "No files found for this period. Upload files first.")

    log = []

    # ── Step 1: Extract business records ────────────────────────────────
    total_extracted = 0
    for f in files:
        mappings = db.query(ColumnMapping).filter(
            ColumnMapping.file_id == f.id,
            ColumnMapping.approved >= 0,
        ).all()
        if not mappings:
            # Try auto-mapping if no confirmed mappings yet
            raw_sample = db.query(RawRecord).filter(RawRecord.file_id == f.id).limit(3).all()
            if raw_sample:
                cols = list(raw_sample[0].raw_data.keys())
                rule_maps = map_columns_rule_based(f.file_type, cols)
                db.query(ColumnMapping).filter(ColumnMapping.file_id == f.id).delete()
                for m in rule_maps:
                    db.add(ColumnMapping(
                        file_id=f.id,
                        raw_column=m["raw_column"],
                        standard_field=m["standard_field"],
                        confidence=m["confidence"],
                        approved=1,
                    ))
                db.commit()
                mappings = db.query(ColumnMapping).filter(
                    ColumnMapping.file_id == f.id,
                    ColumnMapping.approved >= 0,
                ).all()

        raw_records = db.query(RawRecord).filter(RawRecord.file_id == f.id).all()
        if not raw_records or not mappings:
            log.append(f"Skipped {f.filename}: no raw records or mappings")
            continue

        rows = [r.raw_data for r in raw_records]
        mapping_dicts = [{"raw_column": m.raw_column, "standard_field": m.standard_field} for m in mappings]

        # Clear old business records for this file
        old_ids = [br.id for br in db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()]
        if old_ids:
            db.query(ValidationResult).filter(ValidationResult.business_record_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(ImportanceScore).filter(
                ImportanceScore.object_id.in_(old_ids)
            ).delete(synchronize_session=False)
            db.query(JournalEntry).filter(JournalEntry.source_record_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).delete()
        db.commit()

        extracted = extract_records(f.file_type, rows, mapping_dicts, f.id)
        for rec_data in extracted:
            db.add(BusinessRecord(
                file_id=rec_data["file_id"],
                record_type=rec_data["record_type"],
                date=rec_data["date"],
                amount=rec_data["amount"],
                normalized_data=rec_data["normalized_data"],
            ))
        db.commit()
        total_extracted += len(extracted)
        log.append(f"Extracted {len(extracted)} records from {f.filename}")

    # ── Step 2: Process (validate + score + journal entries) ─────────────
    all_records = []
    for f in files:
        recs = db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()
        for r in recs:
            all_records.append({
                "id": r.id, "file_id": r.file_id,
                "record_type": r.record_type, "date": r.date,
                "amount": r.amount, "normalized_data": r.normalized_data,
            })

    if not all_records:
        return {
            "period_id": period_id,
            "pipeline_log": log,
            "warning": "No business records could be extracted. Check that your files have the right columns.",
            "journal_entries": 0,
            "income_statement": None,
            "trial_balance": [],
        }

    file_type_map = {f.id: f.file_type for f in files}

    # Clear old journals and validations
    old_je_ids = [je.id for je in db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()]
    if old_je_ids:
        db.query(JournalLine).filter(JournalLine.entry_id.in_(old_je_ids)).delete(synchronize_session=False)
    db.query(JournalEntry).filter(JournalEntry.period_id == period_id).delete()
    db.query(ValidationResult).filter(ValidationResult.period_id == period_id).delete()
    db.commit()

    # Validate
    all_validations = []
    for f in files:
        recs = [r for r in all_records if r["file_id"] == f.id]
        all_validations.extend(validate_records(recs, file_type_map[f.id], period_id))

    for v in all_validations:
        db.add(ValidationResult(
            period_id=v["period_id"],
            business_record_id=v.get("business_record_id"),
            validation_type=v["validation_type"],
            status=v["status"],
            severity=v["severity"],
            message=v["message"],
        ))
    db.commit()

    # Importance scoring
    scores = score_all_records(all_records, all_validations)
    for s in scores:
        db.add(ImportanceScore(
            object_type=s["object_type"],
            object_id=s["object_id"],
            total_score=s["total_score"],
            level=s["level"],
            reason=s["reason"],
        ))
    db.commit()

    # Journal entries
    journal_entries = map_all_records(all_records, period_id)
    je_objects = []
    for entry_data in journal_entries:
        je = JournalEntry(
            period_id=entry_data["period_id"],
            source_record_id=entry_data["source_record_id"],
            date=entry_data["date"],
            description=entry_data["description"],
            status=entry_data["status"],
        )
        db.add(je)
        db.flush()
        for line_data in entry_data["lines"]:
            db.add(JournalLine(
                entry_id=je.id,
                account_code=line_data["account_code"],
                account_name=line_data["account_name"],
                debit=line_data["debit"],
                credit=line_data["credit"],
            ))
        je_objects.append(entry_data)
    db.commit()
    log.append(f"Created {len(journal_entries)} journal entries")

    # ── Step 3: Generate statements ──────────────────────────────────────
    period = db.query(Period).get(period_id)
    period_label = period.label if period else str(period_id)

    # Re-fetch journal entries for statement generation
    entries_for_stmt = []
    for je in db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all():
        lines = db.query(JournalLine).filter(JournalLine.entry_id == je.id).all()
        entries_for_stmt.append({
            "id": je.id,
            "source_record_id": je.source_record_id,
            "date": je.date,
            "description": je.description,
            "lines": [{"account_code": l.account_code, "account_name": l.account_name,
                       "debit": l.debit, "credit": l.credit} for l in lines],
        })

    trial_balance = generate_trial_balance(entries_for_stmt)
    income_statement = generate_income_statement(entries_for_stmt, period_label)

    # Persist income statement
    db.query(FinancialStatement).filter(FinancialStatement.period_id == period_id).delete()
    db.commit()
    fs = FinancialStatement(period_id=period_id, statement_type="income_statement")
    db.add(fs)
    db.flush()
    for line in income_statement["lines"]:
        db.add(StatementLine(
            statement_id=fs.id,
            line_name=line["line_name"],
            amount=line["amount"],
            account_code=line.get("account_code", ""),
            line_type=line["line_type"],
            evidence_count=line.get("evidence_count", 0),
        ))
    db.commit()
    log.append("Income statement generated")

    val_summary = summarize_validations(all_validations)

    return {
        "period_id": period_id,
        "pipeline_log": log,
        "records_extracted": total_extracted,
        "journal_entries": len(journal_entries),
        "validation_summary": val_summary,
        "income_statement": income_statement,
        "trial_balance": trial_balance,
    }
