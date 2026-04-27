# Architecture

## Current State

The repository currently contains a Telegram bot with Garmin, WHOOP, SQLite, and Anthropic-oriented planner code. Treat this as the current implementation baseline, not the final target.

The target MVP introduces:

- Telegram webhook in production.
- Web Connect UI.
- OpenAI as first AI provider behind a provider abstraction.
- Structured AI output.
- Production Postgres.
- Scheduled sync/recommendation through cron-triggered endpoints.

## Target MVP Components

```text
Telegram
  -> webhook
FastAPI app on Render
  - Telegram update endpoint
  - Web Connect UI
  - WHOOP OAuth callback
  - Garmin connect/session flow
  - Internal sync endpoint
  - Internal daily recommendation endpoint
Postgres on Neon
OpenAI API through AIProvider
Garmin / WHOOP APIs
GitHub Actions cron
```

The app can start as one deployable service. Keep module boundaries clear so worker/scheduler can be split later.

## Deployment MVP

Use:

- Render Free Web Service for the Python web app.
- Neon Free Postgres for production database.
- GitHub Actions cron for scheduled HTTP calls.
- Telegram webhook instead of polling.

Daily schedule:

```text
07:00 Europe/Belgrade - sync + daily recommendation
Additional syncs - 3 to 5 times per day
```

Suggested MVP sync times:

```text
07:00
12:00
17:00
21:00
Europe/Belgrade
```

Scheduled GitHub Actions should call protected internal endpoints. Use a shared secret header, not an unauthenticated public endpoint.

## Local and Production Databases

Local development may use SQLite.

Production must use Postgres.

Rules:

- Use `DATABASE_URL`.
- Keep SQLAlchemy models portable.
- Avoid SQLite-only assumptions.
- Add Alembic before production schema starts changing frequently.
- Current startup `ALTER TABLE` migrations are acceptable only as legacy transitional behavior.

## Raw Data Storage

Store raw provider payloads fully and indefinitely for MVP.

Recommended model:

```text
device_raw_events
- id
- user_id
- provider
- data_type
- external_id
- payload_encrypted
- payload_hash
- source_timestamp
- fetched_at
- parser_version
```

Also store normalized data separately:

- `daily_snapshots`
- `actual_workouts`
- `sleep_records`
- `recovery_metrics`

Use `payload_hash` to avoid duplicate raw event inserts during repeated syncs.

## User and Profile Direction

MVP may remain effectively single-user, but new code should avoid permanent single-user coupling.

Target entities:

```text
users
- id
- telegram_id
- role
- timezone
- created_at

user_training_profiles
- user_id
- max_hr
- max_hr_source
- hr_zone_method
- active_goal_key
- available_training_days
- max_run_days_per_week
- strength_days_per_week
```

Future coach support:

```text
coach_athlete_links
- coach_id
- athlete_id
- status
- permissions
```

## Goals

MVP goal presets:

```text
run_10k_60
run_half_220
run_marathon_finish
```

Represent presets structurally even if they are hard-coded:

```text
goal_type: race_time | finish
sport: run
distance_km: number
target_time_minutes: number | null
```

## Heart Rate Zones

MVP uses max HR based zones.

If max HR is unavailable from devices, ask during onboarding.

Store:

```text
max_hr
max_hr_source: garmin | whoop | manual
hr_zone_method
```

Simple MVP method:

```text
Z1: 50-60%
Z2: 60-70%
Z3: 70-80%
Z4: 80-90%
Z5: 90-100%
```

Later, support threshold-based or provider-supplied zones.

## Device Integration

### WHOOP

Use OAuth. Refresh tokens before expiry. Store tokens encrypted.

### Garmin

Garmin password login is unreliable and has produced `429`.

MVP direction:

- Prefer cached session/token.
- Avoid repeated password login.
- Do not retry aggressively on `429`.
- Mark integration state as `rate_limited` when needed.
- Keep room for a safer web connect flow.

Integration state should include:

```text
provider
status
last_sync_at
last_error
connected_at
```

## Web Connect UI

Telegram `Connect` button creates a one-time link:

```text
https://app-domain/connect?token=...
```

The token must:

- Be random and high entropy.
- Be stored hashed in the database.
- Expire after a short time.
- Be invalidated after use where appropriate.

Web MVP shows only integration cards:

- Garmin status, last sync, connect/update, delete.
- WHOOP status, last sync, connect/update, delete.

No profile, charts, or history in web MVP.

## Sync Policy

Sync providers 3-5 times per day.

At 07:00, sync first, then generate/send daily recommendation.

Later syncs are silent unless new data materially changes the recommendation.

Send a correction when:

- A workout for today appears after the morning recommendation.
- Load becomes materially higher than planned.
- Recovery/readiness changes materially.
- The planned workout is no longer appropriate.

## AI Architecture

Use provider abstraction:

```text
AIProvider
  OpenAIProvider
  FutureProvider
```

OpenAI is the first provider. Do not couple business logic to OpenAI SDK types.

Backend responsibilities:

- Fetch and normalize device data.
- Calculate factual aggregates.
- Calculate weekly volume/load.
- Detect today's workouts.
- Calculate HR zones.
- Build compact AI context.
- Validate AI response.

AI responsibilities:

- Interpret facts.
- Choose recommendation.
- Propose today's workout.
- Explain reasoning.
- Provide avoid/control guidance.

## Structured AI Output

AI must return structured JSON. Backend validates it before saving or displaying.

Draft schema:

```text
readiness_score: 0-100
status_label: string
main_recommendation: string
planned_workout:
  sport: run | bike | swim | strength | walk | mobility | recovery | rest | other
  title: string
  duration_minutes: number | null
  intensity: z1 | z2 | z3 | z4 | z5 | easy | moderate | hard | rest
  blocks:
    - title: string
      duration_minutes: number
      target_hr_zone: string | null
      target_hr_range: string | null
      notes: string | null
reasoning:
  - string
avoid:
  - string
control:
  - string
confidence: low | medium | high
data_gaps:
  - string
```

If data is insufficient, AI must expose `data_gaps` and lower `confidence`.

## Recommendation Persistence

Store recommendations separately from planned workouts.

Suggested records:

```text
daily_recommendations
- id
- user_id
- date
- readiness_score
- status_label
- main_recommendation
- reasoning_json
- avoid_json
- control_json
- confidence
- data_gaps_json
- source_data_hash
- ai_provider
- ai_model
- created_at

planned_workouts
- id
- user_id
- daily_recommendation_id
- date
- sport
- title
- duration_minutes
- intensity
- blocks_json
- source
- status

workout_completions
- id
- planned_workout_id
- user_id
- completion_status
- comment
- created_at
```

`Сделал` / `Не сделал` applies to `planned_workouts`, not general recommendations.

