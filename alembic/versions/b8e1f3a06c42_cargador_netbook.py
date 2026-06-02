"""cargador_netbook en tipo_material

Revision ID: b8e1f3a06c42
Revises: a7b3c5e8d201
Create Date: 2026-06-01

Agrega el tipo 'cargador_netbook' al enum tipo_material.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b8e1f3a06c42'
down_revision: Union[str, Sequence[str], None] = 'a7b3c5e8d201'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tipo_material ADD VALUE IF NOT EXISTS 'cargador_netbook'")


def downgrade() -> None:
    pass  # quitar valores de enum en PG requiere recrear el tipo; no se revierte
