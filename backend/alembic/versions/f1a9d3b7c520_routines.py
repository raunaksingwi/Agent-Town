"""routines

Revision ID: f1a9d3b7c520
Revises: a8c3f6d21b47
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9d3b7c520'
down_revision: Union[str, Sequence[str], None] = 'a8c3f6d21b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('routines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('days', sa.String(length=7), nullable=False),
    sa.Column('at', sa.String(length=5), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_routines_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_routines_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_routines'))
    )
    with op.batch_alter_table('routines', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_routines_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_routines_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_routines_next_run_at'), ['next_run_at'], unique=False)

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('routine_id', sa.Integer(), nullable=True))  # existing runs: all chats
        batch_op.create_index(batch_op.f('ix_runs_routine_id'), ['routine_id'], unique=False)
        batch_op.create_foreign_key(batch_op.f('fk_runs_routine_id_routines'), 'routines', ['routine_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_runs_routine_id_routines'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_runs_routine_id'))
        batch_op.drop_column('routine_id')

    with op.batch_alter_table('routines', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_routines_next_run_at'))
        batch_op.drop_index(batch_op.f('ix_routines_agent_id'))
        batch_op.drop_index(batch_op.f('ix_routines_owner_id'))

    op.drop_table('routines')
