"""mcp headers, env and sign-in

Revision ID: a8c3f6d21b47
Revises: e5b8f1c2a704
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c3f6d21b47'
down_revision: Union[str, Sequence[str], None] = 'e5b8f1c2a704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('mcp_connections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('headers_enc', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('env_enc', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('oauth_enc', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('mcp_connections', schema=None) as batch_op:
        batch_op.drop_column('oauth_enc')
        batch_op.drop_column('env_enc')
        batch_op.drop_column('headers_enc')
