import os
from pathlib import Path


def _load_env_file() -> None:
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        break


_load_env_file()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "6515961910"))
SESSION_TTL_MIN = int(os.environ.get("SESSION_TTL_MIN", "5"))
TZ = os.environ.get("TZ", "Asia/Kolkata")
DIGEST_AT = os.environ.get("DIGEST_AT", "")
ATTENDANCE_THRESHOLD = int(os.environ.get("ATTENDANCE_THRESHOLD", "75"))
FEE_WARN_DAYS = int(os.environ.get("FEE_WARN_DAYS", "7"))
TELEGRAM_EFFECT_ID = os.environ.get("TELEGRAM_EFFECT_ID", "")
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "240"))
LOGIN_RETRIES = int(os.environ.get("LOGIN_RETRIES", "5"))
