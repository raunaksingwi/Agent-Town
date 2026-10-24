"""email verified: when we had proof a user owns their email

Accounts made with Google are verified from the start; password sign-ups aren't, so a Google
sign-in for the same address takes them over instead of joining them (routers/auth.py).

Revision ID: f3b9e6a1c428
Revises: 53ae35cd9aba
Create Date: 2026-10-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b9e6a1c428'
down_revision: Union[str, Sequence[str], None] = '53ae35cd9aba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    # Google already vouched for everyone who signs in with it
    op.execute("UPDATE users SET email_verified_at = created_at WHERE google_sub IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_verified_at')
