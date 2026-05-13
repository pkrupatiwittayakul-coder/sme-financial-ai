"""
Pipeline convenience endpoints.
POST /api/pipeline/schema/{file_id}      — suggest + auto-confirm schema
POST /api/pipeline/{period_id}           — full pipeline (also callable internally)
GET  /api/pipeline/{period_id}/progress  — SSE stream of stage events
"""
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from backend.database import (
    get_db, File as FileModel, RawRecord, ColumnMapping,
    BusinessRecord, ValidationResult, ImportanceScore,
    JournalEntry, JournalLine, FinancialStatement, StatementLine,
    Period, Entity, Relationship
)
from backend.services.schema_mapper import map_columns_rule_based, map_columns_with_llm, merge_mappings
from backend.services.record_extractor import extract_records
from backend.services.validation_engine import validate_records, summarize_validations
from backend.services.importance_scorer import score_all_records
from backend.services.accounting_mapper import map_all_records
from backend.services.statement_generator import generate_income_statement, generate_trial_balance
from backend.services.entity_resolver import extract_entities_from_records, normalize_name
from backend.services.pipeline_progress import (
    reset as pp_reset, update as pp_update, snapshot as pp_snapshot,
)

router = APIRouter()


@router.post("/schema/{file_id}")
def pipeline_schema(file_id: int, db: Session = Depends(get_db)):
    f = db.query(FileModel).get(file_id)
    if not f:
        raise HTTPException(404, "File not found")

    sample = db.query(RawRecord).filter(RawRecord.file_id == file_id).limit(5).all()
    if not sample:
        raise HTTPException(400, "No raw records found. Upload file first.")

    columns = list(sample[0].raw_data.keys())
    sample_rows = [r.raw_data for r in sample]

    rule_mappings = map_columns_rule_based(f.file_type, columns)
    low_conf_cols = [m["raw_column"] for m in rule_mappings if m["confidence"] < 0.70]
    llm_mappings = []
    if low_conf_cols:
        try:
            llm_mappings = map_columns_with_llm(f.file_type, low_conf_cols, sample_rows)
        except Exception:
            pass

    final = merge_mappings(rule_mappings, llm_mappings)
    db.query(ColumnMapping).filter(ColumnMapping.file_id == file_id).delete()
    for m in final:
        db.add(ColumnMapping(
            file_id=file_id,
            raw_column=m["raw_column"],
            standard_field=m["standard_field"],
            confidence=m["confidence"],
            approved=1,
        ))
    db.commit()

    return {
        "file_id": file_id,
        "file_type": f.file_type,
        "mappings_confirmed": len(final),
        "llm_cols_resolved": len(llm_mappings),
    }


def run_pipeline_internal(period_id: int, db: Session) -> dict:
    """
    Full pipeline for a period (called by both the endpoint and upload/auto).
    1. Extract business records from all files with confirmed mappings
    2. Validate + score + create journal entries
    3. Detect date range → update period label
    4. Generate income statement
    5. Build ontology (entities)
    """
    pp_reset(period_id)
    pp_update(period_id, stage="extract", pct=2, message="Pipeline started")

    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    if not files:
        pp_update(period_id, pct=100, status="error", message="No files for this period")
        return {
            "period_id": period_id,
            "pipeline_log": ["No files found for this period"],
            "warning": "Upload files first.",
            "journal_entries": 0,
            "income_statement": None,
            "trial_balance": [],
        }

    log = []
    pp_update(period_id, stage="extract", pct=8, message=f"Found {len(files)} file(s)")

    # ── Step 1: Extract business records ─────────────────────────────────────
    total_extracted = 0
    for f in files:
        mappings = db.query(ColumnMapping).filter(
            ColumnMapping.file_id == f.id,
            ColumnMapping.approved >= 0,
        ).all()
        if not mappings:
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

        old_ids = [br.id for br in db.query(BusinessRecord).filter(BusinessRecord.file_id == f.id).all()]
        if old_ids:
            db.query(ValidationResult).filter(
                ValidationResult.business_record_id.in_(old_ids)
            ).delete(synchronize_session=False)
            db.query(ImportanceScore).filter(
                ImportanceScore.object_id.in_(old_ids)
            ).delete(synchronize_session=False)
            db.query(JournalEntry).filter(
                JournalEntry.source_record_id.in_(old_ids)
            ).delete(synchronize_session=False)
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
        pp_update(
            period_id, stage="extract",
            pct=min(8 + int(27 * (files.index(f) + 1) / max(1, len(files))), 34),
            message=f"Extracted {len(extracted)} records from {f.filename}",
        )

    # ── Step 2: Collect all records ───────────────────────────────────────────
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
        pp_update(period_id, pct=100, status="error",
                  message="No business records could be extracted")
        return {
            "period_id": period_id,
            "pipeline_log": log,
            "warning": "No business records could be extracted. Check your file columns.",
            "journal_entries": 0,
            "income_statement": None,
            "trial_balance": [],
        }

    pp_update(period_id, stage="validate", pct=38,
              message=f"Validating {len(all_records)} records")

    # ── Step 3: Auto-detect date range → update period ────────────────────────
    period = db.query(Period).get(period_id)
    period_label = period.label if period else str(period_id)
    detected_label = period_label

    raw_dates = [r["date"] for r in all_records if r.get("date")]
    if raw_dates:
        raw_dates_sorted = sorted(str(d) for d in raw_dates if d)
        start_date = raw_dates_sorted[0][:10]
        end_date = raw_dates_sorted[-1][:10]
        try:
            from datetime import datetime
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            if sd.year == ed.year and sd.month == ed.month:
                detected_label = sd.strftime("%b %Y")
            elif sd.year == ed.year:
                detected_label = f"{sd.strftime('%b')}–{ed.strftime('%b %Y')}"
            else:
                detected_label = f"{sd.strftime('%b %Y')}–{ed.strftime('%b %Y')}"
        except Exception:
            detected_label = f"{start_date} – {end_date}"

        if period:
            period.label = detected_label
            period.start_date = start_date
            period.end_date = end_date
            db.commit()

        log.append(f"Period detected: {detected_label} ({start_date} → {end_date})")

    # ── Step 4: Validate + score + journal entries ────────────────────────────
    file_type_map = {f.id: f.file_type for f in files}

    old_je_ids = [je.id for je in db.query(JournalEntry).filter(JournalEntry.period_id == period_id).all()]
    if old_je_ids:
        db.query(JournalLine).filter(
            JournalLine.entry_id.in_(old_je_ids)
        ).delete(synchronize_session=False)
    db.query(JournalEntry).filter(JournalEntry.period_id == period_id).delete()
    db.query(ValidationResult).filter(ValidationResult.period_id == period_id).delete()
    db.commit()

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
    pp_update(period_id, stage="validate", pct=52,
              message=f"{len(all_validations)} validation results")

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

    pp_update(period_id, stage="map", pct=60, message="Mapping records to journal entries")
    journal_entries = map_all_records(all_records, period_id)
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
    db.commit()
    log.append(f"Created {len(journal_entries)} journal entries")
    pp_update(period_id, stage="map", pct=78,
              message=f"Created {len(journal_entries)} journal entries")

    # ── Step 5: Generate statements ───────────────────────────────────────────
    pp_update(period_id, stage="generate", pct=82, message="Generating financial statements")
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
    income_statement = generate_income_statement(entries_for_stmt, detected_label)

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
    pp_update(period_id, stage="generate", pct=92, message="Income statement generated")

    # ── Step 6: Ontology (entities) ───────────────────────────────────────────
    db.query(Entity).filter(Entity.period_id == period_id).delete()
    db.commit()

    entity_dicts = extract_entities_from_records(all_records, period_id)
    for ed in entity_dicts:
        db.add(Entity(
            period_id=ed["period_id"],
            entity_type=ed["entity_type"],
            entity_name=ed["entity_name"],
            attributes=ed["attributes"],
        ))
    db.commit()

    entity_counts = {}
    for ed in entity_dicts:
        entity_counts[ed["entity_type"]] = entity_counts.get(ed["entity_type"], 0) + 1

    log.append(f"Ontology: {len(entity_dicts)} entities extracted")
    pp_update(period_id, stage="generate", pct=100, status="completed",
              message=f"Ontology: {len(entity_dicts)} entities; pipeline complete")

    val_summary = summarize_validations(all_validations)

    result = {
        "period_id": period_id,
        "period_label": detected_label,
        "pipeline_log": log,
        "records_extracted": total_extracted,
        "journal_entries": len(journal_entries),
        "validation_summary": val_summary,
        "income_statement": income_statement,
        "trial_balance": trial_balance,
        "entity_counts": entity_counts,
    }
    pp_update(period_id, result=result)
    return result


@router.post("/{period_id}")
def run_pipeline(period_id: int, db: Session = Depends(get_db)):
    files = db.query(FileModel).filter(FileModel.period_id == period_id).all()
    if not files:
        raise HTTPException(404, "No files found for this period. Upload files first.")
    return run_pipeline_internal(period_id, db)


@router.get("/{period_id}/progress")
async def pipeline_progress(period_id: int, request: Request):
    """
    Server-Sent Events stream of the pipeline's current stage / pct / log.
    The dashboard opens an EventSource right before triggering an upload, then
    closes the stream when it receives an event with status='completed' or 'error'.
    Times out after 120 seconds if nothing happens.
    """
    async def event_gen():
        last_payload = None
        last_emit = 0
        # Up to 120 seconds; bail early once pipeline reports a terminal state
        for _ in range(480):
            if await request.is_disconnected():
                break
            snap = pp_snapshot(period_id)
            payload = json.dumps(snap, default=str)
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
                last_emit = 0
            else:
                last_emit += 1
                # Heartbeat every ~5s so proxies don't close the connection
                if last_emit >= 20:
                    yield ": keepalive\n\n"
                    last_emit = 0
            if snap.get("status") in ("completed", "error"):
                break
            await asyncio.sleep(0.25)
        # One final snapshot so the client always sees the end state
        snap = pp_snapshot(period_id)
        yield f"event: progress\ndata: {json.dumps(snap, default=str)}\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # disables nginx/Render buffering
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)
