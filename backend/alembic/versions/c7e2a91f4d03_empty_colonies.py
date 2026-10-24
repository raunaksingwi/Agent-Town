"""empty colonies: ones named before any agents are in them, kept on the user

Revision ID: c7e2a91f4d03
Revises: 263506255f11
Create Date: 2026-10-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2a91f4d03'
down_revision: Union[str, Sequence[str], None] = '263506255f11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('empty_colonies', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('empty_colonies')
