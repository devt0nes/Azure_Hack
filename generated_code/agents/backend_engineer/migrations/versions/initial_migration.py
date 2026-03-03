"""Initial migration

Revision ID: 0001_initial
Revises: 
Create Date: 2023-10-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(open("database_schema.sql", "r").read())

def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")