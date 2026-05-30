"""raton en tipo_material

Revision ID: b2f1a9c4d7e3
Revises: 88614e5a22cc
Create Date: 2026-05-29

Agrega el valor 'raton' al enum tipo_material (PostgreSQL). PG 12+ permite
ADD VALUE dentro de una transacción. IF NOT EXISTS lo hace idempotente.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2f1a9c4d7e3'
down_revision: Union[str, Sequence[str], None] = '88614e5a22cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE tipo_material ADD VALUE IF NOT EXISTS 'raton'")


def downgrade() -> None:
    # Quitar un valor de un enum en PostgreSQL requiere recrear el tipo (riesgoso
    # si hay filas usándolo). No se revierte automáticamente.
    pass
