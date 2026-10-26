"""github pull requests

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26 03:52:32.724582
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('it_artifacts', sa.Column('path', sa.String(length=300), nullable=True))
    op.add_column('it_runs', sa.Column('pr_status', sa.String(length=16), server_default='none', nullable=False))
    op.add_column('it_runs', sa.Column('pr_url', sa.Text(), nullable=True))
    op.add_column('it_runs', sa.Column('pr_number', sa.Integer(), nullable=True))
    op.add_column('it_runs', sa.Column('pr_branch', sa.String(length=200), nullable=True))
    op.add_column('it_runs', sa.Column('pr_error', sa.Text(), nullable=True))
    op.add_column('projects', sa.Column('repo_full_name', sa.String(length=200), nullable=True))
    op.add_column('projects', sa.Column('base_branch', sa.String(length=100), nullable=True))
    # autogenerate doesn't detect CHECK constraints; batch mode makes this work on SQLite too
    with op.batch_alter_table('it_runs') as batch:
        batch.create_check_constraint(
            'pr_status', "pr_status IN ('none', 'pending', 'opened', 'draft', 'skipped', 'failed')")


def downgrade() -> None:
    with op.batch_alter_table('it_runs') as batch:
        batch.drop_constraint(op.f('ck_it_runs_pr_status'), type_='check')
    op.drop_column('projects', 'base_branch')
    op.drop_column('projects', 'repo_full_name')
    op.drop_column('it_runs', 'pr_error')
    op.drop_column('it_runs', 'pr_branch')
    op.drop_column('it_runs', 'pr_number')
    op.drop_column('it_runs', 'pr_url')
    op.drop_column('it_runs', 'pr_status')
    op.drop_column('it_artifacts', 'path')
