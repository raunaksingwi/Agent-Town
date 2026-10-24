"""agent memory

Revision ID: d7a4c2e9f013
Revises: c3d1e5a7b902
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a4c2e9f013'
down_revision: Union[str, Sequence[str], None] = 'c3d1e5a7b902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('memory', sa.Text(), nullable=False, server_default=''))  # existing agents: remember nothing yet


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('memory')
