from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RewardGoal(Base):
    __tablename__ = "reward_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    token_cost: Mapped[int] = mapped_column(Integer)
    deadline: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourceForecast(Base):
    __tablename__ = "resource_forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = mapped_column(Integer)
    available_on: Mapped[date] = mapped_column(Date)
    cadence: Mapped[str] = mapped_column(String(16), default="once")
    note: Mapped[str] = mapped_column(String(200), default="")


class ResetPlan(Base):
    __tablename__ = "reset_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_name: Mapped[str] = mapped_column(String(100))
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    deadline: Mapped[date] = mapped_column(Date)
    current_ship_index: Mapped[int] = mapped_column(Integer, default=0)
    target_resets: Mapped[int] = mapped_column(Integer, default=0)
    completed_cycles: Mapped[int] = mapped_column(Integer, default=0)
    waiting_for_reset: Mapped[bool] = mapped_column(Boolean, default=True)
    ships_json: Mapped[str] = mapped_column(Text, default="[]")
    baseline_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", name="uq_snapshot_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    holiday_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    community_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_xp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elite_commander_xp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battles_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    xp_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boosters_json: Mapped[str] = mapped_column(Text, default="{}")
    ships_json: Mapped[str] = mapped_column(Text, default="[]")
    port_ships_json: Mapped[str] = mapped_column(Text, nullable=True)
    line_state_json: Mapped[str] = mapped_column(Text, default="{}")
    source_status_json: Mapped[str] = mapped_column(Text, default="{}")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManualOverride(Base):
    __tablename__ = "manual_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    field_name: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(Text, default="尚未同步")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
