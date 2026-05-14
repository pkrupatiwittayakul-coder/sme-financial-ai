from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from backend.config import DATABASE_URL

# Engine options differ between SQLite (single-file dev DB) and Postgres (prod).
_engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 300

engine = create_engine(DATABASE_URL, **_engine_kwargs)
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
    label = Column(String)
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
    file_type = Column(String)
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
    approved = Column(Integer, default=0)
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
    record_type = Column(String)
    date = Column(String)
    amount = Column(Float, default=0.0)
    normalized_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    entity_type = Column(String)
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


# ── LLM-designed entity blueprints (Sequence 1 + 2 of the MVP v2) ───────────
class EntityDesign(Base):
    __tablename__ = "entity_designs"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    source_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    entity_key = Column(String, index=True)
    label = Column(String)
    category = Column(String)
    objective = Column(Text)
    department = Column(String)
    constraints = Column(JSON)
    attributes = Column(JSON)
    confidence = Column(Float, default=0.0)
    status = Column(String, default="proposed")
    user_notes = Column(Text)
    position_x = Column(Float, default=200.0)
    position_y = Column(Float, default=200.0)
    color = Column(String, default="#5B4BFB")
    source = Column(String, default="llm")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class EntityRelationDesign(Base):
    __tablename__ = "entity_relation_designs"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    from_key = Column(String)
    to_key = Column(String)
    label = Column(String)
    cardinality = Column(String)
    objective = Column(Text)
    confidence = Column(Float, default=0.0)
    status = Column(String, default="proposed")
    source = Column(String, default="llm")
    created_at = Column(DateTime, default=datetime.utcnow)


class DesignMemory(Base):
    __tablename__ = "design_memory"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    fingerprint = Column(String, index=True)
    file_type = Column(String)
    columns_signature = Column(Text)
    payload = Column(JSON)
    hit_count = Column(Integer, default=0)
    last_used = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    business_record_id = Column(Integer, ForeignKey("business_records.id"), nullable=True)
    validation_type = Column(String)
    status = Column(String)
    severity = Column(String)
    message = Column(Text)


class ImportanceScore(Base):
    __tablename__ = "importance_scores"
    id = Column(Integer, primary_key=True, index=True)
    object_type = Column(String)
    object_id = Column(Integer)
    total_score = Column(Float, default=0.0)
    level = Column(String)
    reason = Column(Text)


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"))
    account_code = Column(String)
    account_name = Column(String)
    account_type = Column(String)
    statement_type = Column(String)


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
    statement_type = Column(String)
    generated_at = Column(DateTime, default=datetime.utcnow)
    lines = relationship("StatementLine", back_populates="statement")


class StatementLine(Base):
    __tablename__ = "statement_lines"
    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("financial_statements.id"))
    line_name = Column(String)
    amount = Column(Float, default=0.0)
    account_code = Column(String)
    line_type = Column(String)
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
    role = Column(String)
    content = Column(Text)
    evidence = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("ChatSession", back_populates="messages")


# ── SQ3: Native Validation Agent findings ───────────────────────────────────
# Each row is one finding the SQ3 agent produced while cross-checking the
# period's data + SQ2 graph against TFRS / IFRS for SMEs.
class AgentValidation(Base):
    __tablename__ = "agent_validations"
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey("periods.id"), index=True)
    sequence = Column(Integer, default=3)        # which pipeline sequence produced it
    standard = Column(String)                    # "TFRS for SMEs" / "IFRS for SMEs"
    section_ref = Column(String)                 # e.g. "Section 23 Revenue"
    rule_code = Column(String)                   # stable code e.g. "REV_CUTOFF"
    rule_name = Column(String)                   # human label
    category = Column(String)                    # revenue / inventory / cutoff / completeness / classification
    status = Column(String, default="warning")   # pass / warning / fail
    severity = Column(String, default="warning") # info / warning / critical
    finding = Column(Text)                       # what the agent observed
    recommendation = Column(Text)                # suggested fix
    affected_entities = Column(JSON)             # list of entity_keys / record ids
    evidence = Column(JSON)                      # supporting numbers / sample rows
    confidence = Column(Float, default=0.0)
    source = Column(String, default="agent")     # agent (LLM) / rule (deterministic)
    ack_status = Column(String, default="open")  # open / acknowledged / dismissed / fixed
    user_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)



def init_db():
    Base.metadata.create_all(bind=engine)
