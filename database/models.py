"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user with device credentials."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(64))

    # WHOOP OAuth tokens (stored as JSON)
    whoop_token: Mapped[dict | None] = mapped_column(JSON)

    # Garmin credentials (stored encrypted in production)
    garmin_email: Mapped[str | None] = mapped_column(String(256))
    garmin_password: Mapped[str | None] = mapped_column(String(256))

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailySnapshot(Base):
    """Cached daily health snapshot (Garmin + WHOOP combined)."""

    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    # WHOOP
    whoop_recovery_score: Mapped[float | None] = mapped_column(Float)
    whoop_hrv_ms: Mapped[float | None] = mapped_column(Float)
    whoop_resting_hr: Mapped[float | None] = mapped_column(Float)
    whoop_strain: Mapped[float | None] = mapped_column(Float)
    whoop_sleep_performance: Mapped[float | None] = mapped_column(Float)
    whoop_sleep_duration_h: Mapped[float | None] = mapped_column(Float)

    # Garmin
    garmin_steps: Mapped[int | None] = mapped_column(Integer)
    garmin_active_calories: Mapped[int | None] = mapped_column(Integer)
    garmin_body_battery_end: Mapped[int | None] = mapped_column(Integer)
    garmin_stress_avg: Mapped[int | None] = mapped_column(Integer)
    garmin_training_readiness: Mapped[int | None] = mapped_column(Integer)

    # Raw JSON for full data
    raw_garmin: Mapped[dict | None] = mapped_column(JSON)
    raw_whoop: Mapped[dict | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class Activity(Base):
    """Individual workout/activity record."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    source: Mapped[str] = mapped_column(String(16))  # 'garmin' | 'whoop'
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)

    sport: Mapped[str] = mapped_column(String(32), index=True)  # running, cycling, etc.
    activity_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    duration_s: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    avg_pace_s_per_km: Mapped[float | None] = mapped_column(Float)
    avg_power_w: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)

    raw_data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class TrainingPlan(Base):
    """AI-generated training plan."""

    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    sport: Mapped[str] = mapped_column(String(32))  # running, cycling, swimming, strength
    plan_type: Mapped[str] = mapped_column(String(32))  # weekly, single_session
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Context snapshot used when generating the plan
    context_snapshot: Mapped[dict | None] = mapped_column(JSON)

    # The plan itself as markdown text
    plan_text: Mapped[str] = mapped_column(Text)
    plan_data: Mapped[dict | None] = mapped_column(JSON)
