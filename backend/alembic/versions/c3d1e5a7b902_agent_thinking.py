"""agent thinking

Revision ID: c3d1e5a7b902
Revises: 9f2ac237d018
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d1e5a7b902'
down_revision: Union[str, Sequence[str], None] = '9f2ac237d018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('thinking', sa.String(length=10), nullable=False, server_default=''))  # existing agents: the model's default


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('thinking')
