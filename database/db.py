from __future__ import annotations

"""Async database access layer.

Sensitive fields are transparently encrypted/decrypted via security.py.
Callers always work with plaintext values — encryption is an internal detail.
"""

import logging
from datetime import datetime
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.future import select

from config import config
from database.models import (
    Activity, Base, ConnectToken, DailySnapshot, TrainingPlan, User,
    UserTrainingProfile, DailyRecommendationRecord,
    PlannedWorkoutRecord, WorkoutCompletion, DeviceRawEvent,
)
from security import decrypt, decrypt_json, encrypt, encrypt_json

logger = logging.getLogger(__name__)

_engine_kwargs: dict = {"echo": False}
if config.DATABASE_NEEDS_SSL:
    import ssl as _ssl
    _ctx = _ssl.create_default_context()
    _engine_kwargs["connect_args"] = {"ssl": _ctx}
engine = create_async_engine(config.DATABASE_URL, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they don't exist, and migrate new columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Add new columns to existing tables (safe to run multiple times)
    new_columns = [
        ("users", "garmin_oauth_token_enc", "TEXT"),
        ("users", "garmin_password_enc", "TEXT"),
        ("users", "whoop_token_enc", "TEXT"),
        ("daily_snapshots", "raw_garmin_enc", "TEXT"),
        ("daily_snapshots", "raw_whoop_enc", "TEXT"),
        ("daily_snapshots", "whoop_avg_hr", "INTEGER"),
        ("daily_snapshots", "whoop_max_hr", "INTEGER"),
        ("daily_snapshots", "whoop_kilojoule", "FLOAT"),
        ("daily_snapshots", "whoop_respiratory_rate", "FLOAT"),
        ("daily_snapshots", "whoop_spo2", "FLOAT"),
        ("daily_snapshots", "whoop_skin_temp", "FLOAT"),
        ("daily_snapshots", "whoop_workout_count", "INTEGER"),
        ("activities", "whoop_strain", "FLOAT"),
    ]
    async with engine.begin() as conn:
        for table, col, col_type in new_columns:
            try:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                )
            except Exception:
                pass  # Column already exists

    logger.info("Database initialised")


# ------------------------------------------------------------------ #
# Users
# ------------------------------------------------------------------ #


async def get_or_create_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(id=telegram_id, username=username, first_name=first_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def update_user_garmin_credentials(
    user_id: int, email: str, password: str
) -> None:
    """Store Garmin credentials — password is Fernet-encrypted before writing."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.garmin_email = email
            user.garmin_password_enc = encrypt(password)
            user.updated_at = datetime.utcnow()
            await session.commit()


async def update_garmin_oauth_token(user_id: int, token_b64: str) -> None:
    """Cache the Garmin OAuth session token (garth base64 dump) encrypted in DB.

    Reusing this on next sync avoids a fresh login → no 429 rate-limit hit.
    """
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.garmin_oauth_token_enc = encrypt(token_b64)
            user.updated_at = datetime.utcnow()
            await session.commit()


async def update_user_whoop_token(user_id: int, token: dict) -> None:
    """Store WHOOP OAuth token — encrypted as JSON before writing."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.whoop_token_enc = encrypt_json(token)
            user.updated_at = datetime.utcnow()
            await session.commit()


async def get_user(user_id: int) -> User | None:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


def get_garmin_password(user: User) -> str | None:
    """Decrypt and return the Garmin password, or None if key mismatch/not set."""
    if not user.garmin_password_enc:
        return None
    try:
        return decrypt(user.garmin_password_enc)
    except ValueError:
        logger.warning("Garmin password decryption failed for user %s — token invalid", user.id)
        return None


def get_whoop_token(user: User) -> dict | None:
    """Decrypt and return the WHOOP token dict, or None if key mismatch/not set."""
    if not user.whoop_token_enc:
        return None
    try:
        return decrypt_json(user.whoop_token_enc)
    except ValueError:
        logger.warning("WHOOP token decryption failed for user %s — token invalid", user.id)
        return None


def get_garmin_oauth_token(user: User) -> str | None:
    """Decrypt and return the cached Garmin OAuth base64 token, or None."""
    if not user.garmin_oauth_token_enc:
        return None
    try:
        return decrypt(user.garmin_oauth_token_enc)
    except ValueError:
        logger.warning("Garmin OAuth token decryption failed for user %s", user.id)
        return None


# ------------------------------------------------------------------ #
# Daily snapshots
# ------------------------------------------------------------------ #


async def upsert_daily_snapshot(
    user_id: int,
    snapshot_date: str,
    whoop_data: dict | None = None,
    garmin_data: dict | None = None,
) -> DailySnapshot:
    async with SessionLocal() as session:
        result = await session.execute(
            select(DailySnapshot).where(
                DailySnapshot.user_id == user_id,
                DailySnapshot.snapshot_date == snapshot_date,
            )
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is None:
            snapshot = DailySnapshot(user_id=user_id, snapshot_date=snapshot_date)
            session.add(snapshot)

        if whoop_data:
            recovery = whoop_data.get("recovery") or {}
            rec_score = recovery.get("score") or {}
            sleep = whoop_data.get("sleep") or {}
            sleep_score = sleep.get("score") or {}
            cycle = whoop_data.get("cycle") or {}
            cycle_score = cycle.get("score") or {}

            snapshot.whoop_recovery_score = rec_score.get("recovery_score")
            snapshot.whoop_hrv_ms = rec_score.get("hrv_rmssd_milli")
            snapshot.whoop_resting_hr = rec_score.get("resting_heart_rate")
            snapshot.whoop_spo2 = rec_score.get("spo2_percentage")
            snapshot.whoop_skin_temp = rec_score.get("skin_temp_celsius")

            snapshot.whoop_strain = cycle_score.get("strain")
            snapshot.whoop_avg_hr = cycle_score.get("average_heart_rate")
            snapshot.whoop_max_hr = cycle_score.get("max_heart_rate")
            snapshot.whoop_kilojoule = cycle_score.get("kilojoule")

            snapshot.whoop_sleep_performance = sleep_score.get("sleep_performance_percentage")
            snapshot.whoop_respiratory_rate = sleep_score.get("respiratory_rate")
            # v2 API nests total_in_bed_time_milli inside stage_summary
            stage = sleep_score.get("stage_summary") or {}
            in_bed_ms = stage.get("total_in_bed_time_milli") or sleep_score.get("total_in_bed_time_milli")
            if in_bed_ms:
                snapshot.whoop_sleep_duration_h = round(in_bed_ms / 3_600_000, 2)

            workouts = whoop_data.get("workouts") or []
            if workouts:
                snapshot.whoop_workout_count = len(workouts)

            # Encrypt raw WHOOP payload before storing
            snapshot.raw_whoop_enc = encrypt_json(whoop_data)

        if garmin_data:
            snapshot.garmin_steps = garmin_data.get("totalSteps")
            snapshot.garmin_active_calories = garmin_data.get("activeKilocalories")
            snapshot.garmin_stress_avg = garmin_data.get("averageStressLevel")
            # Encrypt raw Garmin payload before storing
            snapshot.raw_garmin_enc = encrypt_json(garmin_data)

        await session.commit()
        await session.refresh(snapshot)
        return snapshot


async def get_recent_snapshots(user_id: int, days: int = 7) -> list[DailySnapshot]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(DailySnapshot)
            .where(DailySnapshot.user_id == user_id)
            .order_by(DailySnapshot.snapshot_date.desc())
            .limit(days)
        )
        return list(result.scalars().all())


def decrypt_snapshot_garmin(snapshot: DailySnapshot) -> dict | None:
    """Decrypt and return the raw Garmin payload from a snapshot."""
    return decrypt_json(snapshot.raw_garmin_enc)


def decrypt_snapshot_whoop(snapshot: DailySnapshot) -> dict | None:
    """Decrypt and return the raw WHOOP payload from a snapshot."""
    return decrypt_json(snapshot.raw_whoop_enc)


# ------------------------------------------------------------------ #
# Activities (individual workouts)
# ------------------------------------------------------------------ #


async def save_whoop_workouts(user_id: int, workouts: list[dict]) -> int:
    """Upsert WHOOP workout records into activities table.

    Uses external_id (WHOOP workout id) to avoid duplicates.
    Returns count of newly inserted records.
    """
    if not workouts:
        return 0

    inserted = 0
    async with SessionLocal() as session:
        for w in workouts:
            ext_id = str(w.get("id", ""))
            if not ext_id:
                continue

            result = await session.execute(
                select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.source == "whoop",
                    Activity.external_id == ext_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                continue

            score = w.get("score") or {}  # score can be null for unscored workouts
            # v2 API provides sport_name directly; v1 used sport_id
            sport_name = (
                w.get("sport_name")
                or _whoop_sport_from_id(w.get("sport_id", -1))
            )

            start_str = w.get("start", "")
            act_date = start_str[:10] if start_str else ""

            duration_s = _duration_ms(w) if (w.get("start") and w.get("end")) else None
            kilojoule = score.get("kilojoule")
            calories = round(kilojoule * 0.239) if kilojoule else None

            activity = Activity(
                user_id=user_id,
                source="whoop",
                external_id=ext_id,
                sport=sport_name,
                activity_date=act_date,
                duration_s=duration_s,
                distance_m=score.get("distance_meter"),
                calories=calories,
                avg_hr=score.get("average_heart_rate"),
                max_hr=score.get("max_heart_rate"),
                whoop_strain=score.get("strain"),
            )
            session.add(activity)
            inserted += 1

        await session.commit()
    return inserted


def _duration_ms(w: dict) -> float | None:
    """Calculate duration in seconds from start/end ISO timestamps."""
    try:
        from datetime import datetime as _dt
        s = _dt.fromisoformat(w["start"].replace("Z", "+00:00"))
        e = _dt.fromisoformat(w["end"].replace("Z", "+00:00"))
        return (e - s).total_seconds()
    except Exception:
        return None


def _whoop_sport_from_id(sport_id: int) -> str:
    from integrations.whoop import WHOOP_SPORTS
    return WHOOP_SPORTS.get(sport_id, f"sport_{sport_id}")


async def save_garmin_activities(user_id: int, activities: list[dict]) -> int:
    """Upsert Garmin activity records into activities table.

    Uses activityId as external_id to avoid duplicates.
    Returns count of newly inserted records.
    """
    if not activities:
        return 0

    _GARMIN_SPORT_MAP = {
        "running": "running",
        "trail_running": "running",
        "treadmill_running": "running",
        "cycling": "cycling",
        "road_biking": "cycling",
        "mountain_biking": "cycling",
        "indoor_cycling": "cycling",
        "open_water_swimming": "swimming",
        "lap_swimming": "swimming",
        "strength_training": "strength",
        "indoor_cardio": "functional_fitness",
        "hiit": "hiit",
        "yoga": "yoga",
        "pilates": "pilates",
        "rowing": "rowing",
        "indoor_rowing": "rowing",
        "triathlon": "triathlon",
        "walking": "walking",
        "hiking": "hiking",
        "tennis": "tennis",
        "boxing": "boxing",
        "cross_training": "functional_fitness",
        "resort_skiing_snowboarding": "ski",
        "skiing": "ski",
    }

    inserted = 0
    async with SessionLocal() as session:
        for a in activities:
            ext_id = str(a.get("activityId", ""))
            if not ext_id:
                continue

            result = await session.execute(
                select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.source == "garmin",
                    Activity.external_id == ext_id,
                )
            )
            if result.scalar_one_or_none():
                continue

            raw_sport = (
                a.get("activityType", {}).get("typeKey", "activity")
                if isinstance(a.get("activityType"), dict)
                else "activity"
            )
            sport = _GARMIN_SPORT_MAP.get(raw_sport, raw_sport)

            start_str = a.get("startTimeLocal") or a.get("startTimeGMT") or ""
            act_date = start_str[:10] if start_str else ""

            distance_m = a.get("distance") or None
            duration_s = a.get("duration") or None
            avg_hr = a.get("averageHR") or None
            max_hr = a.get("maxHR") or None
            calories = a.get("calories") or None
            elevation = a.get("elevationGain") or None

            avg_speed = a.get("averageSpeed")  # m/s
            avg_pace = None
            if avg_speed and avg_speed > 0:
                avg_pace = 1000.0 / avg_speed  # s/km

            avg_power = a.get("avgPower") or None
            avg_cadence = a.get("averageRunningCadenceInStepsPerMinute") or a.get("averageCadence") or None

            activity = Activity(
                user_id=user_id,
                source="garmin",
                external_id=ext_id,
                sport=sport,
                activity_date=act_date,
                duration_s=duration_s,
                distance_m=distance_m,
                calories=calories,
                avg_hr=avg_hr,
                max_hr=max_hr,
                avg_pace_s_per_km=avg_pace,
                avg_power_w=avg_power,
                avg_cadence=avg_cadence,
                elevation_gain_m=elevation,
            )
            session.add(activity)
            inserted += 1

        await session.commit()
    return inserted
    try:
        from datetime import datetime as _dt
        s = _dt.fromisoformat(w["start"].replace("Z", "+00:00"))
        e = _dt.fromisoformat(w["end"].replace("Z", "+00:00"))
        return (e - s).total_seconds()
    except Exception:
        return None


async def get_recent_activities(
    user_id: int, days: int = 28, source: str | None = None
) -> list[Activity]:
    """Return activities for the last N days, newest first."""
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    async with SessionLocal() as session:
        q = (
            select(Activity)
            .where(Activity.user_id == user_id, Activity.activity_date >= cutoff)
            .order_by(Activity.activity_date.desc())
        )
        if source:
            q = q.where(Activity.source == source)
        result = await session.execute(q)
        return list(result.scalars().all())


# ------------------------------------------------------------------ #
# Training plans
# ------------------------------------------------------------------ #


async def save_training_plan(
    user_id: int,
    sport: str,
    plan_type: str,
    plan_text: str,
    recovery_score: float | None = None,
    hrv: float | None = None,
    readiness: int | None = None,
) -> TrainingPlan:
    async with SessionLocal() as session:
        plan = TrainingPlan(
            user_id=user_id,
            sport=sport,
            plan_type=plan_type,
            plan_text=plan_text,
            recovery_score_at_gen=recovery_score,
            hrv_at_gen=hrv,
            readiness_at_gen=readiness,
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return plan


async def get_latest_plan(user_id: int, sport: str) -> TrainingPlan | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(TrainingPlan)
            .where(
                TrainingPlan.user_id == user_id,
                TrainingPlan.sport == sport,
            )
            .order_by(TrainingPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


# ------------------------------------------------------------------ #
# User training profile
# ------------------------------------------------------------------ #


async def get_training_profile(user_id: int) -> UserTrainingProfile | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserTrainingProfile).where(UserTrainingProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def upsert_training_profile(
    user_id: int,
    max_hr: int | None = None,
    max_hr_source: str | None = None,
    active_goal_key: str | None = None,
    available_training_days: list[str] | None = None,
    max_run_days_per_week: int | None = None,
    strength_days_per_week: int | None = None,
    onboarding_done: bool | None = None,
) -> UserTrainingProfile:
    import json as _json
    async with SessionLocal() as session:
        result = await session.execute(
            select(UserTrainingProfile).where(UserTrainingProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = UserTrainingProfile(user_id=user_id)
            session.add(profile)

        if max_hr is not None:
            profile.max_hr = max_hr
        if max_hr_source is not None:
            profile.max_hr_source = max_hr_source
        if active_goal_key is not None:
            profile.active_goal_key = active_goal_key
        if available_training_days is not None:
            profile.available_training_days = _json.dumps(available_training_days)
        if max_run_days_per_week is not None:
            profile.max_run_days_per_week = max_run_days_per_week
        if strength_days_per_week is not None:
            profile.strength_days_per_week = strength_days_per_week
        if onboarding_done is not None:
            profile.onboarding_done = onboarding_done

        profile.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(profile)
        return profile


# ------------------------------------------------------------------ #
# Daily recommendations & planned workouts
# ------------------------------------------------------------------ #


async def save_daily_recommendation(
    user_id: int,
    date: str,
    rec: "DailyRecommendation",  # ai.schemas.DailyRecommendation
    source_data_hash: str | None = None,
    ai_provider: str = "openai",
    ai_model: str = "gpt-4o",
) -> tuple[DailyRecommendationRecord, PlannedWorkoutRecord]:
    """Persist a validated DailyRecommendation. Returns (rec_record, workout_record)."""
    import json as _json

    async with SessionLocal() as session:
        rec_record = DailyRecommendationRecord(
            user_id=user_id,
            date=date,
            readiness_score=rec.readiness_score,
            status_label=rec.status_label,
            main_recommendation=rec.main_recommendation,
            reasoning_json=_json.dumps(rec.reasoning, ensure_ascii=False),
            avoid_json=_json.dumps(rec.avoid, ensure_ascii=False),
            control_json=_json.dumps(rec.control, ensure_ascii=False),
            data_gaps_json=_json.dumps(rec.data_gaps, ensure_ascii=False),
            confidence=rec.confidence,
            source_data_hash=source_data_hash,
            ai_provider=ai_provider,
            ai_model=ai_model,
        )
        session.add(rec_record)
        await session.flush()  # get rec_record.id

        w = rec.planned_workout
        blocks = [b.model_dump() for b in w.blocks]
        workout_record = PlannedWorkoutRecord(
            user_id=user_id,
            daily_recommendation_id=rec_record.id,
            date=date,
            sport=w.sport,
            title=w.title,
            duration_minutes=w.duration_minutes,
            intensity=w.intensity,
            blocks_json=_json.dumps(blocks, ensure_ascii=False),
        )
        session.add(workout_record)
        await session.commit()
        await session.refresh(rec_record)
        await session.refresh(workout_record)
        return rec_record, workout_record


async def get_daily_recommendation(
    user_id: int, date: str
) -> DailyRecommendationRecord | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(DailyRecommendationRecord)
            .where(
                DailyRecommendationRecord.user_id == user_id,
                DailyRecommendationRecord.date == date,
            )
            .order_by(DailyRecommendationRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_planned_workout(
    user_id: int, date: str
) -> PlannedWorkoutRecord | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(PlannedWorkoutRecord)
            .where(
                PlannedWorkoutRecord.user_id == user_id,
                PlannedWorkoutRecord.date == date,
            )
            .order_by(PlannedWorkoutRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_recent_recommendations(
    user_id: int, days: int = 7
) -> list[DailyRecommendationRecord]:
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    async with SessionLocal() as session:
        result = await session.execute(
            select(DailyRecommendationRecord)
            .where(
                DailyRecommendationRecord.user_id == user_id,
                DailyRecommendationRecord.date >= cutoff,
            )
            .order_by(DailyRecommendationRecord.date.desc())
        )
        return list(result.scalars().all())


async def save_workout_completion(
    planned_workout_id: int,
    user_id: int,
    completion_status: str,  # done|skipped
    comment: str | None = None,
) -> WorkoutCompletion:
    async with SessionLocal() as session:
        completion = WorkoutCompletion(
            planned_workout_id=planned_workout_id,
            user_id=user_id,
            completion_status=completion_status,
            comment=comment,
        )
        session.add(completion)
        await session.commit()
        await session.refresh(completion)
        return completion


# ------------------------------------------------------------------ #
# Device raw events
# ------------------------------------------------------------------ #


async def save_raw_event(
    user_id: int,
    provider: str,
    data_type: str,
    payload: dict,
    external_id: str | None = None,
    source_timestamp: str | None = None,
    parser_version: str = "1",
) -> bool:
    """Store raw provider event. Returns True if inserted, False if duplicate."""
    import hashlib
    import json as _json

    payload_str = _json.dumps(payload, sort_keys=True, ensure_ascii=False)
    payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()

    async with SessionLocal() as session:
        result = await session.execute(
            select(DeviceRawEvent).where(
                DeviceRawEvent.user_id == user_id,
                DeviceRawEvent.payload_hash == payload_hash,
            )
        )
        if result.scalar_one_or_none():
            return False  # duplicate

        event = DeviceRawEvent(
            user_id=user_id,
            provider=provider,
            data_type=data_type,
            external_id=external_id,
            payload_encrypted=encrypt_json(payload),
            payload_hash=payload_hash,
            source_timestamp=source_timestamp,
            parser_version=parser_version,
        )
        session.add(event)
        await session.commit()
        return True


# ------------------------------------------------------------------ #
# Web connect tokens
# ------------------------------------------------------------------ #


async def create_connect_token(user_id: int, ttl_minutes: int = 15) -> str:
    """Create a one-time connect token. Returns the raw (unhashed) token."""
    import hashlib
    import secrets
    from datetime import timedelta

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.utcnow() + timedelta(minutes=ttl_minutes)

    async with SessionLocal() as session:
        ct = ConnectToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(ct)
        await session.commit()

    return raw_token


async def validate_connect_token(raw_token: str) -> int | None:
    """Validate and consume a connect token. Returns user_id or None."""
    import hashlib

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    async with SessionLocal() as session:
        result = await session.execute(
            select(ConnectToken).where(
                ConnectToken.token_hash == token_hash,
                ConnectToken.used == False,
                ConnectToken.expires_at > datetime.utcnow(),
            )
        )
        ct = result.scalar_one_or_none()
        if not ct:
            return None

        ct.used = True
        await session.commit()
        return ct.user_id
