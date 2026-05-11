import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/sme_financial.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/sme_uploads")
REPORT_DIR = os.getenv("REPORT_DIR", "/tmp/sme_reports")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
