"""Add sentiment_score to relationships

Revision ID: f1d2e3a4b5c6
Revises: 9a3b7c2d1e4f
Create Date: 2025-01-19 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f1d2e3a4b5c6'
down_revision = '9a3b7c2d1e4f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sentiment_score column to relationships table
    op.add_column('relationships',
        sa.Column('sentiment_score', sa.Integer(), nullable=False, server_default='0')
    )

    # Backfill existing records with neutral sentiment (0)
    # Note: server_default='0' handles this automatically for new rows


def downgrade() -> None:
    # Remove sentiment_score column
    op.drop_column('relationships', 'sentiment_score')
