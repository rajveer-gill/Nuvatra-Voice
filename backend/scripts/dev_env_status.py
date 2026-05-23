"""Print which backend/.env keys are set (no secret values). Used by scripts/dev-check.ps1."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

for key in (
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "CLERK_JWKS_URL",
    "CLERK_SECRET_KEY",
    "ADMIN_CLERK_USER_IDS",
    "CLIENT_ID",
    "FRONTEND_URL",
):
    print(f"{key}={'set' if (os.getenv(key) or '').strip() else 'unset'}")
