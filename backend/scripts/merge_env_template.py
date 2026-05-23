"""Merge existing backend/.env values into LOCAL-DEV template (no stdout secrets)."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / ".env"
existing: dict[str, str] = {}
for line in p.read_text(encoding="utf-8").splitlines():
    s = line.strip()
    if not s or s.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    existing[k.strip()] = v.strip()


def emit(key: str, default: str = "", *, comment: str | None = None) -> list[str]:
    out: list[str] = []
    if comment:
        out.append(f"# {comment}")
    v = existing.get(key, default)
    out.append(f"{key}={v}" if v else f"{key}=")
    return out


blocks: list[str] = [
    "# Nuvatra Voice - LOCAL backend/.env",
    "# Paste values from Render -> API service -> Environment (same variable names).",
    "# Docker Postgres: from repo root run:  docker compose up -d",
    "# Then uncomment DATABASE_URL for local Docker below.",
    "",
    *emit("OPENAI_API_KEY", comment="Required"),
    "",
    "# --- Database (pick ONE) ---",
    "# Local Docker (safe for wiping test data):",
    "# DATABASE_URL=postgresql://nuvatra:nuvatra_dev@localhost:5432/nuvatra",
    "# Or paste from Render (production data - careful):",
    *emit("DATABASE_URL"),
    "",
    "# --- Clerk (copy from Render) ---",
    *emit("CLERK_JWKS_URL", comment="Render: CLERK_JWKS_URL"),
    *emit("CLERK_SECRET_KEY", comment="Render: CLERK_SECRET_KEY"),
    *emit("ADMIN_CLERK_USER_IDS", comment="Render: ADMIN_CLERK_USER_IDS"),
    *emit("FRONTEND_URL", "http://localhost:3000"),
    "",
    "# --- Twilio ---",
    *emit("TWILIO_ACCOUNT_SID"),
    *emit("TWILIO_AUTH_TOKEN"),
    *emit("TWILIO_PHONE_NUMBER"),
    "# NGROK_URL=",
    "# PUBLIC_BASE_URL=",
    "",
    "# --- Optional (paste from Render if used in prod) ---",
    "# STRIPE_SECRET_KEY=",
    "# STRIPE_WEBHOOK_SECRET=",
    "# SENTRY_DSN=",
    "# CLIENT_ID=",
    "",
    "# NEXT_PUBLIC_* vars belong in repo root .env.local (not this file).",
    "# Removed NEXT_PUBLIC_API_URL from here - keep it only in .env.local",
]

p.write_text("\n".join(blocks) + "\n", encoding="utf-8")
print("OK")
