"""colonies: a team's name and what it's for, kept on its lead

Revision ID: e5d08788f6b8
Revises: e9c4b2d7a316
Create Date: 2026-10-15 13:09:47.104873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5d08788f6b8'
down_revision: Union[str, Sequence[str], None] = 'e9c4b2d7a316'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('colony_name', sa.String(length=60), server_default='', nullable=False))
        batch_op.add_column(sa.Column('colony_about', sa.String(length=300), server_default='', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('colony_about')
        batch_op.drop_column('colony_name')
