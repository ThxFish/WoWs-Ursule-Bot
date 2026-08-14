"""Ursule Bot baseline schema."""

from alembic import op

from ursule_bot.core.database import Base
from ursule_bot.core import system_models  # noqa: F401
from ursule_bot.centers.planning import models  # noqa: F401


revision = "0001_ursule_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
