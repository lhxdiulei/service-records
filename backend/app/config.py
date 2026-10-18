import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres@127.0.0.1:55432/service_records')
DATA_DIR = Path(os.getenv('DATA_DIR', str(ROOT.parent / 'data')))
ORIGINS = set(os.getenv('APP_ORIGINS', 'http://localhost:8088,http://127.0.0.1:8088,http://127.0.0.1:5173').split(','))
SECURE_COOKIE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
WORKFLOW_DIR = ROOT / 'workflows'
MAX_FILE_BYTES = 10 * 1024 * 1024
SESSION_HOURS = 12
