"""push_subscription (suscripciones Web Push para avisos de vencimiento)

Revision ID: e5c3d9f2a1b6
Revises: d4b7e2f1a8c9
Create Date: 2026-05-30

Tabla de suscripciones Web Push: endpoint único + claves del cliente, por persona.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5c3d9f2a1b6'
down_revision: Union[str, Sequence[str], None] = 'd4b7e2f1a8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("persona.id"), nullable=False, index=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("creado_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )


def downgrade() -> None:
    op.drop_table("push_subscription")
