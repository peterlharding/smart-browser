"""Initial schema.

Creates the target schema on a new database: identity, the bookmark/user_bookmark split,
a global tag vocabulary, and tag links carrying provenance. See doc/architecture.md §2 and
ADRs 0001, 0002 and 0006.

`bookmark_content` and `tag_centroid` are deliberately absent. They are the only tables
needing pgvector, and they arrive at M3 with the crawler that fills them.

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.Text()),
        sa.Column("email", sa.Text()),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "user_identity",
        sa.Column("provider", sa.String(32), primary_key=True),
        # Google's `sub`, GitHub's numeric id: immutable, unlike email.
        sa.Column("provider_subject", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_at_link", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("user_identity_user_idx", "user_identity", ["user_id"])

    op.create_table(
        "bookmark",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        # The duplication guarantee lives here. Everything else about idempotent saving
        # is convenience; this constraint is what makes it true.
        sa.Column("url_hash", sa.LargeBinary(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("site", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.UniqueConstraint("url_hash", name="bookmark_url_hash_uniq"),
    )
    op.create_index("bookmark_site_idx", "bookmark", ["site"])

    op.create_table(
        "user_bookmark",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bookmark_id", sa.Integer(),
                  sa.ForeignKey("bookmark.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title_override", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("saved_from", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("last_visited_at", sa.DateTime(timezone=True)),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "bookmark_id", name="user_bookmark_uniq"),
    )
    op.create_index("user_bookmark_user_idx", "user_bookmark", ["user_id"])
    op.create_index("user_bookmark_bookmark_idx", "user_bookmark", ["bookmark_id"])

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Lowercased by the application on every write path, so UNIQUE is sufficient and
        # no citext extension is needed.
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("tag.id", ondelete="SET NULL")),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(trim(name)) > 0", name="tag_name_not_blank"),
    )

    op.create_table(
        "tag_alias",
        sa.Column("alias", sa.Text(), primary_key=True),
        sa.Column("tag_id", sa.Integer(),
                  sa.ForeignKey("tag.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("tag_alias_tag_idx", "tag_alias", ["tag_id"])

    op.create_table(
        "bookmark_tag",
        sa.Column("user_bookmark_id", sa.Integer(),
                  sa.ForeignKey("user_bookmark.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(),
                  sa.ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "source",
            sa.Enum("user", "ai", "rule", "import", name="tag_source"),
            nullable=False,
            server_default="user",
        ),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    # The lookup the entire product depends on: "everything tagged python".
    op.create_index("bookmark_tag_tag_idx", "bookmark_tag", ["tag_id", "user_bookmark_id"])


def downgrade() -> None:
    op.drop_table("bookmark_tag")
    op.drop_table("tag_alias")
    op.drop_table("tag")
    op.drop_table("user_bookmark")
    op.drop_table("bookmark")
    op.drop_table("user_identity")
    op.drop_table("app_user")
    sa.Enum(name="tag_source").drop(op.get_bind(), checkfirst=True)
