# Implementation Roadmap

This roadmap keeps changes reviewable and reversible. Each phase should normally be a separate branch and PR unless the user explicitly asks otherwise.

Before starting any task, ask whether to create a new branch from `main` or continue from the current git state.

## Branch Verification Rule

Every branch needs an explicit verification checklist before PR.

Minimum:

- Run `venv/bin/python scripts/check_baseline.py`.
- State whether app runtime was started.
- State whether Telegram or web UI was manually checked.
- Record any known untested area.

For Telegram changes:

- Run the bot locally.
- Inspect terminal logs while the user exercises the flow in Telegram.
- Use the user's screenshots or report as part of verification.

For web changes:

- Run the web app locally.
- Inspect backend terminal logs while the user exercises the browser UI.
- Use screenshots or a clear user report as part of verification.

## Task Size Rule

Good task size:

- One coherent behavior or architecture slice.
- Can be reviewed in one sitting.
- Can be reverted without breaking unrelated completed work.
- Has a concrete verification step.

Avoid:

- Giant PRs that change bot UI, database, AI, integrations, and deploy at once.
- Tiny PRs that only move one line without reducing risk.
- Mixing refactors with behavior changes unless the refactor is required for that behavior.

## Phase 0 - Baseline Hygiene

Goal: make current state inspectable and safer to change.

Tasks:

1. Add or confirm basic local commands for running the bot and minimal import checks.
2. Document current env variables and remove outdated provider assumptions where safe.
3. Add a lightweight test/check command if none exists.

Verification:

- `venv/bin/python scripts/check_baseline.py` passes.
- Config validation behavior is understood.
- No secrets or local DB/cache files are staged.

## Phase 1 - AI Provider Abstraction

Goal: decouple planning logic from a specific provider.

Tasks:

1. Introduce provider-neutral interfaces and request/response models.
2. Implement OpenAI as the first provider.
3. Keep legacy planner behavior working until replacement is complete.
4. Add validation for structured daily recommendation output.

Verification:

- Unit/import checks pass.
- A mocked provider can return a valid structured recommendation.
- Invalid AI JSON fails validation safely.

## Phase 2 - Data Model Foundation

Goal: add persistent structures needed for daily assistant without switching every runtime concern at once.

Tasks:

1. Add user training profile fields/entities: max HR, goal, available days, weekly limits.
2. Add goal presets.
3. Add daily recommendation and planned workout persistence.
4. Add workout completion/comment persistence.
5. Add raw device event storage with hash-based deduplication.

Verification:

- Local DB initializes or migrates.
- Existing encrypted token behavior still works.
- Duplicate raw payloads are not inserted repeatedly.

## Phase 3 - Telegram MVP Flows

Goal: expose the core MVP through Telegram while keeping existing flows stable where possible.

Tasks:

1. Implement `/start` onboarding: max HR, goal, training days, run days/week, strength/week.
2. Implement menu buttons: Today, Goal, Profile, Connect, History.
3. Implement Today using current available data and structured recommendation formatting.
4. Implement 7-day History.
5. Implement planned workout feedback: `Сделал`, `Не сделал`, comment.

Verification:

- Manual Telegram flow works locally.
- User can complete onboarding once and not repeat it every time.
- Today and History work when integrations are missing and when data exists.

## Phase 4 - Sync and Recommendation Engine

Goal: make recommendations data-driven and idempotent.

Tasks:

1. Normalize Garmin/WHOOP activities into common activity types.
2. Calculate weekly load and volume by sport.
3. Detect workouts already completed today.
4. Build backend facts context for AI.
5. Implement recommendation update policy for silent sync vs user notification.

Verification:

- Sync can run multiple times without duplicating raw events.
- Garmin `429` does not trigger aggressive retry loops.
- A workout detected after the morning recommendation can trigger a correction.

## Pre-requisites before Phase 5

These must be completed manually before Phase 5 code can be written or tested.
Phase 5 requires a public HTTPS URL for WHOOP OAuth redirect and a production database.

### 1. Render — web hosting

- Register at [render.com](https://render.com) (free tier is sufficient for MVP).
- Create a Web Service connected to the GitHub repo.
- Note the assigned URL: `https://<your-app>.onrender.com`
- Do not deploy yet — Render config (`render.yaml`) will be added in Phase 6.

### 2. Neon — production Postgres

- Register at [neon.tech](https://neon.tech) (free tier is sufficient for MVP).
- Create a new project.
- Copy the connection string (`postgresql://...`) — this becomes `DATABASE_URL` in production.

### 3. WHOOP developer app — update redirect URI

- Go to [developer.whoop.com](https://developer.whoop.com) → your app settings.
- Add or update the Redirect URI to: `https://<your-app>.onrender.com/auth/whoop/callback`
- The old local/ngrok redirect URI can be kept alongside it for local testing.

### 4. Domain (optional for MVP)

- The `*.onrender.com` domain is sufficient for WHOOP OAuth and MVP Web Connect UI.
- A custom domain can be added to Render later without code changes.

---

## Phase 5 - Web Connect UI

Goal: move sensitive connection flows out of regular Telegram dialogs.
Requires: Pre-requisites above completed (Render URL known, Neon DATABASE_URL ready, WHOOP redirect URI updated).

Tasks:

1. Add FastAPI app entrypoint alongside the existing polling bot.
2. Add one-time connect token model and service.
3. Add Connect button in Telegram that generates a web link.
4. Add minimal Web Connect UI with Garmin and WHOOP cards.
5. Add WHOOP OAuth callback endpoint through web backend.
6. Add Garmin token/session-first connection handling via web.

Verification:

- FastAPI app starts locally alongside polling bot.
- Connect links expire and cannot be reused incorrectly.
- Integration statuses show connected/not connected/error/last sync.
- Tokens/credentials are encrypted.
- WHOOP OAuth flow completes end-to-end with real redirect URI.

## Phase 6 - Webhook and Deployment MVP

Goal: make the app run outside local polling.

Tasks:

1. Introduce FastAPI app entrypoint.
2. Add Telegram webhook endpoint.
3. Add protected internal sync/recommendation endpoints.
4. Add Render deployment config.
5. Add Neon Postgres configuration.
6. Add GitHub Actions cron for sync/recommendation calls.

Verification:

- Local webhook app starts.
- Protected endpoints reject missing/invalid secret.
- Render deploy has required env variables documented.
- GitHub Actions cron can call the intended endpoint.

## Phase 7 - Hardening

Goal: reduce operational and security risk before broader use.

Tasks:

1. Add structured logging without leaking raw health data or secrets.
2. Add backup/export/delete planning for user data.
3. Add error monitoring path.
4. Add minimal test suite around critical services.

Verification:

- Logs do not expose tokens, passwords, raw payloads, or API keys.
- Failure modes are visible to the user where appropriate.
- Critical services have tests or documented manual checks.
