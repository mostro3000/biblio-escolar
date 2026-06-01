"""debe_cambiar_password en persona (clave temporal = DNI, cambio obligado al primer login)

Revision ID: f6d4a1b9c2e7
Revises: e5c3d9f2a1b6
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f6d4a1b9c2e7'
down_revision: Union[str, Sequence[str], None] = 'e5c3d9f2a1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("persona", sa.Column(
        "debe_cambiar_password", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("persona", "debe_cambiar_password")
