"""Async database access layer."""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.future import select

from config import config
from database.models import Base, DailySnapshot, TrainingPlan, User

logger = logging.getLogger(__name__)

engine = create_async_engine(config.DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


async def update_user_whoop_token(user_id: int, token: dict) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.whoop_token = token
            user.updated_at = datetime.utcnow()
            await session.commit()


async def update_user_garmin_credentials(
    user_id: int, email: str, password: str
) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.garmin_email = email
            user.garmin_password = password
            user.updated_at = datetime.utcnow()
            await session.commit()


async def get_user(user_id: int) -> User | None:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


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
            recovery = whoop_data.get("recovery", {})
            rec_score = recovery.get("score", {})
            sleep = whoop_data.get("sleep", {})
            sleep_score = sleep.get("score", {})
            cycle = whoop_data.get("cycle", {})

            snapshot.whoop_recovery_score = rec_score.get("recovery_score")
            snapshot.whoop_hrv_ms = rec_score.get("hrv_rmssd_milli")
            snapshot.whoop_resting_hr = rec_score.get("resting_heart_rate")
            snapshot.whoop_strain = cycle.get("score", {}).get("strain")
            snapshot.whoop_sleep_performance = sleep_score.get(
                "sleep_performance_percentage"
            )
            if sleep.get("score", {}).get("total_in_bed_time_milli"):
                snapshot.whoop_sleep_duration_h = round(
                    sleep_score["total_in_bed_time_milli"] / 3_600_000, 2
                )
            snapshot.raw_whoop = whoop_data

        if garmin_data:
            snapshot.garmin_steps = garmin_data.get("totalSteps")
            snapshot.garmin_active_calories = garmin_data.get("activeKilocalories")
            snapshot.garmin_stress_avg = garmin_data.get("averageStressLevel")
            snapshot.raw_garmin = garmin_data

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


# ------------------------------------------------------------------ #
# Training plans
# ------------------------------------------------------------------ #


async def save_training_plan(
    user_id: int,
    sport: str,
    plan_type: str,
    plan_text: str,
    context_snapshot: dict | None = None,
    plan_data: dict | None = None,
) -> TrainingPlan:
    async with SessionLocal() as session:
        plan = TrainingPlan(
            user_id=user_id,
            sport=sport,
            plan_type=plan_type,
            plan_text=plan_text,
            context_snapshot=context_snapshot,
            plan_data=plan_data,
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
