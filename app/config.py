import os
from dotenv import load_dotenv
load_dotenv()
APP_VERSION = "1.4.4"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
DB_PATH = os.getenv("VERITY_DB_PATH", "app/data/verity.db")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
# Pause between claims so a 13-claim audit does not burst through free-tier per-minute limits.
CLAIM_DELAY_SECONDS = float(os.getenv("VERITY_CLAIM_DELAY", "1.0"))
