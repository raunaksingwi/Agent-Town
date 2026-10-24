"""mail index: who people email, open loops, and routines that start on new email

Revision ID: c8d2f5e1a093
Revises: b2e7c4a9d151
Create Date: 2026-10-13 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d2f5e1a093'
down_revision: Union[str, Sequence[str], None] = 'b2e7c4a9d151'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('mail_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('gmail_id', sa.String(length=40), nullable=False),
    sa.Column('thread_id', sa.String(length=40), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('from_me', sa.Boolean(), nullable=False),
    sa.Column('sender', sa.String(length=320), nullable=False),
    sa.Column('people', sa.JSON(), nullable=False),
    sa.Column('subject_enc', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['oauth_accounts.id'], name=op.f('fk_mail_messages_account_id_oauth_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_messages')),
    sa.UniqueConstraint('account_id', 'gmail_id', name=op.f('uq_mail_messages_account_id'))
    )
    with op.batch_alter_table('mail_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_messages_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_messages_at'), ['at'], unique=False)
        batch_op.create_index(batch_op.f('ix_mail_messages_thread_id'), ['thread_id'], unique=False)

    op.create_table('mail_people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('sent', sa.Integer(), nullable=False),
    sa.Column('received', sa.Integer(), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['oauth_accounts.id'], name=op.f('fk_mail_people_account_id_oauth_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mail_people')),
    sa.UniqueConstraint('account_id', 'email', name=op.f('uq_mail_people_account_id'))
    )
    with op.batch_alter_table('mail_people', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mail_people_account_id'), ['account_id'], unique=False)

    with op.batch_alter_table('oauth_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('index_on', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('index_history', sa.String(length=40), server_default='', nullable=False))
        batch_op.add_column(sa.Column('index_synced_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('index_claimed_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('index_detail', sa.String(length=300), server_default='', nullable=False))

    with op.batch_alter_table('routines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trigger', sa.String(length=10), server_default='schedule', nullable=False))
        batch_op.add_column(sa.Column('seen_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('routines', schema=None) as batch_op:
        batch_op.drop_column('seen_until')
        batch_op.drop_column('trigger')
    with op.batch_alter_table('oauth_accounts', schema=None) as batch_op:
        batch_op.drop_column('index_detail')
        batch_op.drop_column('index_claimed_until')
        batch_op.drop_column('index_synced_at')
        batch_op.drop_column('index_history')
        batch_op.drop_column('index_on')
    with op.batch_alter_table('mail_people', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_people_account_id'))
    op.drop_table('mail_people')
    with op.batch_alter_table('mail_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mail_messages_thread_id'))
        batch_op.drop_index(batch_op.f('ix_mail_messages_at'))
        batch_op.drop_index(batch_op.f('ix_mail_messages_account_id'))
    op.drop_table('mail_messages')
