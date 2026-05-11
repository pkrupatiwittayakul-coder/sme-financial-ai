from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from backend.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── ORM Models ──────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    companies = relationship("Company", back_populates="owner")


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    industry = Column(String)
    currency = Column(String, default="THB")
    created_at = Column(DateTime, default=datetime.utcnow)
    periods = relationship("Period", back_populates="company")
    owner = relationship("User", back_populates="companies")


class Period(Base):
    __tablename__ = "periods"
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    label = Column(String)          # e.g. "Jan 2026"
    start_date = Column(String)
    end_date = Column(String)
    status = Column(String, default="open")
    company = relationship("Company", back_populates="periods")
    files = relationship("File", back_populates="period")


class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    filename = Column(String)
    path = Column(String)
    file_type = Column(String)          # sales / purchase / inventory / coa / unknown
    business_process = Column(String)
    classification_confidence = Column(Float, default=0.0)
    row_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    period = relationship("Period", back_populates="files")
    raw_records = relationship("RawRecord", back_populates="file")
    column_mappings = relationship("ColumnMapping", back_populates="file")


class ColumnMapping(Base):
    __tablename__ = "column_mappings"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    raw_column = Column(String)
    standard_field = Column(String)
    confidence = Column(Float, default=0.0)
    approved = Column(Integer, default=0)   # 0=pending, 1=approved, -1=rejected
    file = relationship("File", back_populates="column_mappings")


class RawRecord(Base):
    __tablename__ = "raw_records"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    row_number = Column(Integer)
    raw_data = Column(JSON)
    file = relationship("File", back_populates="raw_records")


class BusinessRecord(Base):
    __tablename__ = "business_records"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    raw_record_id = Column(Integer, ForeignKey("raw_records.id"), nullable=True)
    record_type = Column(String)    # SalesTransaction / SupplierInvoice / InventoryMovement
    date = Column(String)
    amount = Column(Float, default=0.0)
    normalized_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    entity_type = Column(String)    # Branch / SKU / Supplier / Account / Customer
    entity_name = Column(String)
    attributes = Column(JSON)


class Relationship(Base):
    __tablename__ = "relationships"
    id = Column(Integer, primary_key=True, index=True)
    source_entity_id = Column(Integer, ForeignKey("entities.id"))
    relationship_type = Column(String)
    target_entity_id = Column(Integer, ForeignKey("entities.id"))
    evidence = Column(Text)
    business_record_id = Column(Integer, ForeignKey("business_records.id"), nullable=True)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    business_record_id = Column(Integer, ForeignKey("business_records.id"), nullable=True)
    validation_type = Column(String)
    status = Column(String)         # passed / warning / failed
    severity = Column(String)       # info / warning / critical
    message = Column(Text)


class ImportanceScore(Base):
    __tablename__ = "importance_scores"
    id = Column(Integer, primary_key=True, index=True)
    object_type = Column(String)
    object_id = Column(Integer)
    total_score = Column(Float, default=0.0)
    level = Column(String)          # Low / Medium / High / Critical
    reason = Column(Text)


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    account_code = Column(String)
    account_name = Column(String)
    account_type = Column(String)   # Asset / Liability / Equity / Revenue / Expense
    statement_type = Column(String) # IS / BS


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    source_record_id = Column(Integer, ForeignKey("business_records.id"), nullable=True)
    date = Column(String)
    description = Column(Text)
    status = Column(String, default="posted")
    lines = relationship("JournalLine", back_populates="entry")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id"))
    account_id = Column(Integer, ForeignKey("accounts.id"))
    account_code = Column(String)
    account_name = Column(String)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    entry = relationship("JournalEntry", back_populates="lines")


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    statement_type = Column(String)  # income_statement / trial_balance
    generated_at = Column(DateTime, default=datetime.utcnow)
    lines = relationship("StatementLine", back_populates="statement")


class StatementLine(Base):
    __tablename__ = "statement_lines"
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("financial_statements.id"))
    line_name = Column(String)
    amount = Column(Float, default=0.0)
    account_code = Column(String)
    line_type = Column(String)      # revenue / cogs / gross_profit / expense / net_profit
    evidence_count = Column(Integer, default=0)
    statement = relationship("FinancialStatement", back_populates="lines")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    messages = relationship("ChatMessage", back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"))
    role = Column(String)           # user / assistant
    content = Column(Text)
    evidence = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("ChatSession", back_populates="messages")



class FileSheet(Base):
    """Track individual sheets within a multi-sheet Excel file."""
    __tablename__ = "file_sheets"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    sheet_name = Column(String)
    row_count = Column(Integer, default=0)
    columns = Column(JSON)


class StatementEvidence(Base):
    """
    Evidence trail: links each StatementLine back to source BusinessRecords.
    Satisfies: 'every statement line should answer where did this number come from'.
    """
    __tablename__ = "statement_evidence"
    id = Column(Integer, primary_key=True, index=True)
    statement_line_id = Column(Integer, ForeignKey("statement_lines.id"))
    business_record_id = Column(Integer, ForeignKey("business_records.id"), nullable=True)
    raw_record_id = Column(Integer, ForeignKey("raw_records.id"), nullable=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    journal_entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=True)
    amount_contribution = Column(Float, default=0.0)


def init_db():
    Base.metadata.create_all(bind=engine)
