# Redis security checklist and runbook

Render Redis stores **live voice call session state** (caller metadata, conversation context, response polling). Treat compromise of Redis as **PII exposure**.

Keys used by the app: `call:{CallSid}`, `call:{CallSid}:resp`, `call:{CallSid}:ulock`.

See also [PRODUCTION-ENV.md](./PRODUCTION-ENV.md), [render.yaml](../render.yaml), and Admin → **Production ops** (automated checks).

---

## Pre-deploy checklist (Render Dashboard)

Run once after creating or changing Redis, and again after any security incident.

### 1. Private networking

1. Open **Render Dashboard** → **Redis** → `nuvatra-voice-redis`.
2. Go to **Access Control** (or **Networking**).
3. Confirm **`ipAllowList` is empty** — no entries, especially **not** `0.0.0.0/0`.
4. Empty allowlist means **only linked Render services** in your account can connect on the private network.

The blueprint sets `ipAllowList: []` in [render.yaml](../render.yaml). **Never add `0.0.0.0/0`.**

### 2. Internal URL only

1. Open **Web Service** → `nuvatra-voice-backend` → **Environment**.
2. Confirm `REDIS_URL` is **linked** from the Redis service (`fromService` in blueprint), not pasted from an external vendor console.
3. Do **not** set `REDIS_URL` on Vercel or any client-facing env.

### 3. Credential hygiene

- Never commit `REDIS_URL` to git, paste it in tickets, or send it to client-side code.
- Application logs must not print the URL (only error types on connection failure).
- If credentials may have leaked, follow the **rotation runbook** below.

### 4. TLS expectations

| Connection type | URL scheme | Notes |
|-----------------|------------|--------|
| Render internal (recommended) | `redis://` | Private network between services; normal for blueprint-linked Redis |
| External Redis | `rediss://` | Requires TLS, certificate verification, and a **minimal** IP allowlist |

Do not expose Redis to the public internet without TLS and a narrow CIDR allowlist.

### 5. Production readiness (automated)

After deploy, open **Admin → Production ops** and confirm:

| Check | Must pass for Deepgram / multi-worker |
|-------|----------------------------------------|
| REDIS_URL set | Yes |
| Redis reachable (PING) | Yes |
| Voice state on Redis | Yes |
| Redis config consistent | Yes (critical — false means silent fallback to memory) |
| Redis production ready | Yes |

Do **not** enable `VOICE_STT_PROVIDER=deepgram` until **Redis production ready** is green.

For local dev without Redis, set `VOICE_STATE_BACKEND=memory` explicitly so ops checks are not misread.

---

## Incident / credential rotation runbook

### Suspected credential leak

1. **Render Dashboard** → Redis → **Regenerate credentials** (or create new Redis and relink if your plan requires it).
2. Confirm `nuvatra-voice-backend` env `REDIS_URL` updated (linked services auto-update on redeploy).
3. **Redeploy** the backend web service.
4. **Admin → Production ops** → Refresh → confirm **Redis PING** and **Redis production ready** are green.
5. Review Render logs for `redis_ops_ping_failed` or `redis_call_session_store_failed` during the window.

### Persistent PING failure

If Redis is unreachable, the app may **fall back to in-memory** call state per worker:

- Multi-worker voice breaks (split state).
- Deepgram streaming breaks across workers.
- Treat as **Sev-1** until Redis is restored and **Redis config consistent** is green again.

### Data classification reminder

Session payloads can include phone numbers, names discussed on calls, and booking context. Purge is handled by TTL (30 minutes) and call cleanup; legal holds do not apply to ephemeral Redis keys but do apply to DB rows.

---

## Manual verification command (optional)

After deploy, headers on the API are separate; for Redis, rely on Admin ops panel.

```bash
# Health only — does not expose Redis details
curl -sf "https://nuvatra-voice.onrender.com/api/health"
```

Admin self-check requires a valid admin Bearer token; use the **Production ops** panel in the app instead of curl.
