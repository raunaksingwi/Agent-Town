"""caretaker runs

Revision ID: 263506255f11
Revises: b3db92974558
Create Date: 2026-10-16 13:03:44.863762

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '263506255f11'
down_revision: Union[str, Sequence[str], None] = 'b3db92974558'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('caretaker_turns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('state', sa.String(length=10), server_default='done', nullable=False))
        batch_op.add_column(sa.Column('run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('layout', sa.JSON(), nullable=False, server_default='{}'))
        batch_op.create_foreign_key(batch_op.f('fk_caretaker_turns_run_id_runs'), 'runs', ['run_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=12), server_default='agent', nullable=False))
        batch_op.alter_column('agent_id',
               existing_type=sa.INTEGER(),
               nullable=True)



def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM runs WHERE agent_id IS NULL")    # the caretaker's own runs have no agent
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.alter_column('agent_id',
               existing_type=sa.INTEGER(),
               nullable=False)
        batch_op.drop_column('kind')

    with op.batch_alter_table('caretaker_turns', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_caretaker_turns_run_id_runs'), type_='foreignkey')
        batch_op.drop_column('layout')
        batch_op.drop_column('run_id')
        batch_op.drop_column('state')

