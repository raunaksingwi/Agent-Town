"""email rules: when an agent's email may go out on its own

Revision ID: b2e7c4a9d151
Revises: f1a9d3b7c520
Create Date: 2026-10-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e7c4a9d151'
down_revision: Union[str, Sequence[str], None] = 'f1a9d3b7c520'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_policy', sa.JSON(), server_default='{}', nullable=False))
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('untrusted', sa.String(length=200), server_default='', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_column('untrusted')
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('email_policy')
