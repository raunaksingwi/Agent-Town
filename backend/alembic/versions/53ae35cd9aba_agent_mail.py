"""agent mail

Colonies write to each other, and to the person, by mail (app/mail.py): threads with the loop
guard's counters, the mail itself, which agent is the mayor, and which runs nobody is watching.

Revision ID: 53ae35cd9aba
Revises: d4f8b2c61e07
Create Date: 2026-10-17 13:34:48.025801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53ae35cd9aba'
down_revision: Union[str, Sequence[str], None] = 'd4f8b2c61e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mail_threads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('paused_reason', sa.String(length=300), nullable=False),
    sa.Column('started_by_id', sa.Integer(), nullable=True),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('hops', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('max_hops', sa.Integer(), nullable=False),
    sa.Column('max_cost_usd', sa.Float(), nullable=False),
    sa.Column('open_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mail_threads_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['mail_threads.id'], name=op.f('fk_mail_threads_parent_id_mail_threads'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['started_by_id'], ['agents.id'], name=op.f('fk_mail_threads_started_by_id_agents'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_threads'))
    )
    with op.batch_alter_table('mail_threads', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_threads_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_threads_parent_id'), ['parent_id'], unique=False)

    op.create_table('mail',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=False),
    sa.Column('from_id', sa.Integer(), nullable=True),
    sa.Column('to_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('state', sa.String(length=10), nullable=False),
    sa.Column('from_run_id', sa.Integer(), nullable=True),
    sa.Column('run_id', sa.Integer(), nullable=True),
    sa.Column('untrusted', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['from_id'], ['agents.id'], name=op.f('fk_mail_from_id_agents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['from_run_id'], ['runs.id'], name=op.f('fk_mail_from_run_id_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_mail_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_mail_run_id_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['thread_id'], ['mail_threads.id'], name=op.f('fk_mail_thread_id_mail_threads'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_id'], ['agents.id'], name=op.f('fk_mail_to_id_agents'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail'))
    )
    with op.batch_alter_table('mail', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_state'), ['state'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_thread_id'), ['thread_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_to_id'), ['to_id'], unique=False)

    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=12), server_default='', nullable=False))

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unattended', sa.Boolean(), server_default=sa.text('(false)'), nullable=False))
        batch_op.add_column(sa.Column('thread_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_runs_thread_id_mail_threads'), 'mail_threads', ['thread_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('mayor_checked_at', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('mayor_checked_at')

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_runs_thread_id_mail_threads'), type_='foreignkey')
        batch_op.drop_column('thread_id')
        batch_op.drop_column('unattended')

    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_column('role')

    with op.batch_alter_table('mail', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_to_id'))
        batch_op.drop_index(batch_op.f('ix_mail_thread_id'))
        batch_op.drop_index(batch_op.f('ix_mail_state'))
        batch_op.drop_index(batch_op.f('ix_mail_owner_id'))

    op.drop_table('mail')
    with op.batch_alter_table('mail_threads', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_threads_parent_id'))
        batch_op.drop_index(batch_op.f('ix_mail_threads_owner_id'))

    op.drop_table('mail_threads')
