"""raspberry en tipo_material

Revision ID: c3a2b8e1f6d4
Revises: b2f1a9c4d7e3
Create Date: 2026-05-29

Agrega el valor 'raspberry' (Raspberry Pi 400) al enum tipo_material.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c3a2b8e1f6d4'
down_revision: Union[str, Sequence[str], None] = 'b2f1a9c4d7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tipo_material ADD VALUE IF NOT EXISTS 'raspberry'")


def downgrade() -> None:
    pass  # quitar valores de enum en PG requiere recrear el tipo; no se revierte
