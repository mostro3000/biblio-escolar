"""directivo en rol

Revision ID: d4b7e2f1a8c9
Revises: c3a2b8e1f6d4
Create Date: 2026-05-29

Agrega el rol 'directivo' al enum rol (audita reportes + opera mostrador).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd4b7e2f1a8c9'
down_revision: Union[str, Sequence[str], None] = 'c3a2b8e1f6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE rol ADD VALUE IF NOT EXISTS 'directivo'")


def downgrade() -> None:
    pass  # quitar valores de enum en PG requiere recrear el tipo; no se revierte
