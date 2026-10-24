"""houses saved from their colony

A moved house (users.town) used to be saved in tiles from the town square; now it's saved from its
colony's corner, so it moves with its colony. The old spots would land somewhere else, so houses go back
into their blocks (the files and library buildings were, and still are, counted from the square). The
same goes for the town a caretaker turn would put back on Undo.

Revision ID: 7c2e4a9d1b30
Revises: 06169b5c4ccd
Create Date: 2026-10-17 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c2e4a9d1b30'
down_revision: Union[str, Sequence[str], None] = '06169b5c4ccd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOUSES = ("agent:", "shared:")


def _without_houses(town: dict) -> dict:
    return {k: v for k, v in town.items() if not k.startswith(HOUSES)}


def upgrade() -> None:
    conn = op.get_bind()
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("town", sa.JSON))
    for id_, town in conn.execute(sa.select(users.c.id, users.c.town)).all():
        if town and _without_houses(town) != town:
            conn.execute(users.update().where(users.c.id == id_).values(town=_without_houses(town)))
    turns = sa.table("caretaker_turns", sa.column("id", sa.Integer), sa.column("undo", sa.JSON(none_as_null=True)))
    for id_, undo in conn.execute(sa.select(turns.c.id, turns.c.undo).where(turns.c.undo.is_not(None))).all():
        if isinstance(undo, dict) and isinstance(undo.get("town"), dict) and _without_houses(undo["town"]) != undo["town"]:
            conn.execute(turns.update().where(turns.c.id == id_).values(undo={**undo, "town": _without_houses(undo["town"])}))


def downgrade() -> None:
    """Nothing to put back: houses stand in their blocks either way."""
