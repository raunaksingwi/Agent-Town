"""web connections: the base URL encrypted, only its scheme and host shown

Some APIs put their key in the URL's path, so a web connection's base URL is kept like its
Authorization header: url_enc holds it encrypted, url only what the app shows (app/webapi.py).

Revision ID: b7d2e4f9a613
Revises: f3b9e6a1c428
Create Date: 2026-10-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.security import decrypt, encrypt
from app.webapi import shown


# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f9a613'
down_revision: Union[str, Sequence[str], None] = 'f3b9e6a1c428'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('mcp_connections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('url_enc', sa.Text(), nullable=True))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, url FROM mcp_connections WHERE transport = 'web' AND url IS NOT NULL")).all()
    for id_, url in rows:
        conn.execute(sa.text("UPDATE mcp_connections SET url = :shown, url_enc = :enc WHERE id = :id"),
                     {"shown": shown(url), "enc": encrypt(url), "id": id_})


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, url_enc FROM mcp_connections WHERE url_enc IS NOT NULL")).all()
    for id_, enc in rows:
        conn.execute(sa.text("UPDATE mcp_connections SET url = :url WHERE id = :id"), {"url": decrypt(enc), "id": id_})
    with op.batch_alter_table('mcp_connections', schema=None) as batch_op:
        batch_op.drop_column('url_enc')
