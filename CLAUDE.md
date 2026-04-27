# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Multi-Agent Project Context

This repository is also worked on by other LLM agents. Before making product, architecture, or implementation-scope decisions, read:

- `AGENTS.md`
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/AGENT_ROLES.md`

The sections below describe the current/legacy implementation mechanics. The target MVP has moved toward a daily assistant with Telegram webhook, Web Connect UI, OpenAI behind a provider abstraction, Neon Postgres, Render deployment, and GitHub Actions cron. If this file conflicts with `AGENTS.md` or `docs/`, treat the conflict as a migration gap and report it before changing behavior.

## Communication Language

Always communicate with the user in **Russian**. All responses, explanations, and questions must be in Russian.

## Running the Bot

```bash
# Setup
cp .env.example .env         # fill in all required values
python -c "import secrets; print(secrets.token_hex(32))"  # generate SECRET_KEY

pip install -r requirements.txt

# Run
python -m bot.main
```

No test suite or linter is configured yet.

## Required Environment Variables

Validated at startup in `config.Config.validate()` — missing values crash immediately:

| Variable | How to get |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `ADMIN_TELEGRAM_ID` | @userinfobot (your personal numeric ID) |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ANTHROPIC_API_KEY` | console.anthropic.com |

Optional (set per-account in bot settings): `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI`.

**`SECRET_KEY` must never change after first run** — all encrypted DB fields become unreadable.

## Architecture

Single-user personal bot (only `ADMIN_TELEGRAM_ID` can interact). All handlers are wrapped with `auth()` from `bot/auth.py`.

### Data Flow

```
Telegram → AuthMiddleware → handler
                               │
                    ┌──────────┴──────────┐
                    │                     │
             GarminClient          WhoopClient
             (garminconnect)       (httpx + OAuth2)
                    │                     │
                    └──────────┬──────────┘
                               │
                    upsert_daily_snapshot()
                    (encrypt raw payloads → SQLite)
                               │
                    TrainingPlanner (Claude Sonnet)
                    ← AthleteContext built from snapshots
```

### Key Modules

**`bot/main.py`** — builds the Application, registers all handlers in order (specific before generic, Q&A catch-all must be last).

**`bot/auth.py`** — `AuthMiddleware` wraps every `BaseHandler`. Uses `getattr(inner, "callback", _dummy_callback)` because `ConversationHandler` has no `.callback`.

**`security.py`** — Fernet encryption (PBKDF2 from `SECRET_KEY`). Callers always pass plaintext; encrypt/decrypt is internal to `database/db.py` helpers (`get_garmin_password`, `get_whoop_token`, `get_garmin_oauth_token`). These return `None` on decryption failure instead of raising.

**`integrations/garmin.py`** — `GarminClient.connect_cached(email, password, token_b64)` avoids 429 by reusing the cached garth OAuth token (`garth.loads(token_b64)`). Falls back to password login, then saves the fresh token via `update_garmin_oauth_token()`. Retries on 429 with backoff `(5s, 15s, 30s)`.

**`integrations/whoop.py`** — WHOOP API v1 OAuth 2.0. Token refresh happens automatically 5 min before expiry. In-memory cache `_TOKEN_STORE[user_id]` per process lifetime; tokens also persisted encrypted in DB.

**`training/planner.py`** — `AthleteContext` dataclass aggregates all health metrics into a prompt. `TrainingPlanner` calls Claude via `anthropic.AsyncAnthropic`. System prompt is a Russian-speaking elite coach. Token budgets: weekly plan 2048, session 1024, recovery analysis 800.

**`database/models.py`** — Uses `Optional[X]` (not `X | None`) in all `Mapped[]` columns — required for Python 3.9 compatibility because SQLAlchemy evaluates annotations at runtime via `eval()`.

**`database/db.py`** — `init_db()` runs idempotent `ALTER TABLE ADD COLUMN` migrations on startup (try/except to skip existing columns).

### Telegram Bot Patterns

- **ConversationHandler** (Garmin credential setup): entry via `CallbackQueryHandler` on `^settings:`, states `GARMIN_EMAIL → GARMIN_PASSWORD`.
- **Long text**: plans >3800 chars are split at newlines into ≤4000-char chunks.
- **Context data**: `context.user_data` stores temporary Garmin email during conversation, cleared after save.

## Deployment

```bash
# Fly.io (free tier)
fly launch --no-deploy
fly volumes create health_bot_data --size 1 --region ams
fly secrets set TELEGRAM_BOT_TOKEN=... ADMIN_TELEGRAM_ID=... SECRET_KEY=... ANTHROPIC_API_KEY=...
fly deploy
```

- Polling bot — no HTTP port exposed, no webhooks needed.
- SQLite persisted at `/data/health_bot.db` on a Fly volume (configured via `DATABASE_URL` env var in Dockerfile).
- Python 3.12-slim image, non-root user `botuser`.
