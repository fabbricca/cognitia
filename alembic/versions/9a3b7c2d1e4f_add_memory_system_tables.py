"""Add memory system tables

Revision ID: 9a3b7c2d1e4f
Revises: 5ea8724a9737
Create Date: 2025-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9a3b7c2d1e4f'
down_revision = '5ea8724a9737'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### Create memories table ###
    op.create_table(
        'memories',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('character_id', sa.CHAR(36), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('memory_type', sa.String(50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('emotional_tone', sa.String(50), nullable=True),
        sa.Column('importance', sa.Numeric(3, 2), default=0.5),
        sa.Column('source_chat_id', sa.CHAR(36), sa.ForeignKey('chats.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_message_ids', sa.Text(), nullable=True),  # JSON for SQLite, ARRAY for Postgres
        sa.Column('last_accessed', sa.DateTime(), default=sa.func.now()),
        sa.Column('access_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_memories_user_character', 'memories', ['user_id', 'character_id'])
    op.create_index('ix_memories_type', 'memories', ['memory_type'])
    op.create_index('ix_memories_importance', 'memories', ['importance'])

    # ### Create user_facts table ###
    op.create_table(
        'user_facts',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('character_id', sa.CHAR(36), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Numeric(3, 2), default=1.0),
        sa.Column('source_memory_id', sa.CHAR(36), sa.ForeignKey('memories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_user_facts_lookup', 'user_facts', ['user_id', 'character_id', 'category'])
    op.create_unique_constraint('uq_user_facts_key', 'user_facts', ['user_id', 'character_id', 'key'])

    # ### Create relationships table ###
    op.create_table(
        'relationships',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('character_id', sa.CHAR(36), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage', sa.String(50), default='stranger'),
        sa.Column('trust_level', sa.Integer(), default=0),
        sa.Column('total_conversations', sa.Integer(), default=0),
        sa.Column('total_messages', sa.Integer(), default=0),
        sa.Column('first_conversation', sa.DateTime(), nullable=True),
        sa.Column('last_conversation', sa.DateTime(), nullable=True),
        sa.Column('inside_jokes', sa.Text(), nullable=True),  # JSON
        sa.Column('milestones', sa.Text(), nullable=True),  # JSON
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_unique_constraint('uq_relationships', 'relationships', ['user_id', 'character_id'])

    # ### Create diary_entries table ###
    op.create_table(
        'diary_entries',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('character_id', sa.CHAR(36), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('entry_type', sa.String(20), default='daily'),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('highlights', sa.Text(), nullable=True),  # JSON
        sa.Column('emotional_summary', sa.String(100), nullable=True),
        sa.Column('topics_discussed', sa.Text(), nullable=True),  # JSON
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_unique_constraint('uq_diary_entries', 'diary_entries', ['user_id', 'character_id', 'entry_date', 'entry_type'])
    op.create_index('ix_diary_entries_date', 'diary_entries', ['user_id', 'character_id', 'entry_date'])


def downgrade() -> None:
    op.drop_table('diary_entries')
    op.drop_table('relationships')
    op.drop_table('user_facts')
    op.drop_table('memories')
