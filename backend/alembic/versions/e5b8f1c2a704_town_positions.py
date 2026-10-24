"""town positions

Revision ID: e5b8f1c2a704
Revises: d7a4c2e9f013
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b8f1c2a704'
down_revision: Union[str, Sequence[str], None] = 'd7a4c2e9f013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('town', sa.JSON(), nullable=False, server_default='{}'))  # nothing moved yet


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('town')
