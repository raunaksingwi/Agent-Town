"""colonies of one: an agent with a colony name leads a colony, team or not

Until now a colony name on an agent without a team meant nothing (a lead whose team was emptied kept it).
It would now make that agent a colony of one, so those leftover names go.

Revision ID: d4f8b2c61e07
Revises: 7c2e4a9d1b30
Create Date: 2026-10-17 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f8b2c61e07'
down_revision: Union[str, Sequence[str], None] = '7c2e4a9d1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE agents SET colony_name = '', colony_about = '' "
               "WHERE colony_name != '' AND id NOT IN (SELECT lead_id FROM agent_team)")


def downgrade() -> None:
    pass
