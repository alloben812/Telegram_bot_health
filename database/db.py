"""Async database access layer.

Sensitive fields are transparently encrypted/decrypted via security.py.
Callers always work with plaintext values — encryption is an internal detail.
"""

from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.future import select

from config import config
from database.models import Activity, Base, DailySnapshot, TrainingPlan, User
from security import decrypt, decrypt_json, encrypt, encrypt_json

logger = logging.getLogger(__name__)

engine = create_async_engine(config.DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they don't exist, and migrate new columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Add new columns to existing tables (safe to run multiple times)
    new_columns = [
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
    """Decrypt and return the Garmin password, or None if not set."""
    if not user.garmin_password_enc:
        return None
    return decrypt(user.garmin_password_enc)


def get_whoop_token(user: User) -> dict | None:
    """Decrypt and return the WHOOP token dict, or None if not set."""
    if not user.whoop_token_enc:
        return None
    return decrypt_json(user.whoop_token_enc)


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
