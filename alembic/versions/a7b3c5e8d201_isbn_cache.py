"""isbn_cache (caché de lookups de ISBN online)

Revision ID: a7b3c5e8d201
Revises: f6d4a1b9c2e7
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7b3c5e8d201'
down_revision: Union[str, Sequence[str], None] = 'f6d4a1b9c2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "isbn_cache",
        sa.Column("isbn", sa.String(length=20), primary_key=True),
        sa.Column("titulo", sa.String(length=300), nullable=True),
        sa.Column("autor", sa.String(length=200), nullable=True),
        sa.Column("editorial", sa.String(length=160), nullable=True),
        sa.Column("anio", sa.Integer(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("fuente", sa.String(length=20), nullable=True),
        sa.Column("creado_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("isbn_cache")
