"""caretaker

Revision ID: b3db92974558
Revises: e5d08788f6b8
Create Date: 2026-10-16 12:22:48.218613

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3db92974558'
down_revision: Union[str, Sequence[str], None] = 'e5d08788f6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('caretaker_turns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('conversation', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('messages', sa.JSON(), nullable=False),
    sa.Column('reply', sa.Text(), nullable=False),
    sa.Column('actions', sa.JSON(), nullable=False),
    sa.Column('proposals', sa.JSON(), nullable=False),
    sa.Column('undo', sa.JSON(), nullable=True),
    sa.Column('undone', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_caretaker_turns_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_caretaker_turns'))
    )
    with op.batch_alter_table('caretaker_turns', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_caretaker_turns_owner_id'), ['owner_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('map_style', sa.String(length=20), server_default='', nullable=False))
        batch_op.add_column(sa.Column('caretaker_conversation', sa.Integer(), server_default='1', nullable=False))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('caretaker_conversation')
        batch_op.drop_column('map_style')

    with op.batch_alter_table('caretaker_turns', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_caretaker_turns_owner_id'))

    op.drop_table('caretaker_turns')
