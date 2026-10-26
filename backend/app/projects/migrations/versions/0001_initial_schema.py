"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-26 03:11:17.660665
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    sa.UniqueConstraint('name', name=op.f('uq_projects_name'))
    )
    op.create_table('it_runs',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('assumptions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('analysis', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('review', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('review_verdict', sa.String(length=32), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('running', 'done', 'failed')", name=op.f('ck_it_runs_status')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_it_runs_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_it_runs'))
    )
    op.create_index('ix_it_runs_project_created', 'it_runs', ['project_id', 'created_at'], unique=False)
    op.create_table('it_artifacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('agent', sa.String(length=16), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['it_runs.id'], name=op.f('fk_it_artifacts_run_id_it_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_it_artifacts'))
    )
    op.create_index(op.f('ix_it_artifacts_run_id'), 'it_artifacts', ['run_id'], unique=False)
    op.create_table('it_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('assignee', sa.String(length=16), nullable=False),
    sa.Column('depends_on', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('done_when', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('todo', 'doing', 'done')", name=op.f('ck_it_tasks_status')),
    sa.ForeignKeyConstraint(['run_id'], ['it_runs.id'], name=op.f('fk_it_tasks_run_id_it_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_it_tasks')),
    sa.UniqueConstraint('run_id', 'code', name='uq_it_tasks_run_code')
    )
    op.create_index(op.f('ix_it_tasks_run_id'), 'it_tasks', ['run_id'], unique=False)
    op.create_table('qa_findings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('agent', sa.String(length=16), nullable=False),
    sa.Column('issue', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['it_runs.id'], name=op.f('fk_qa_findings_run_id_it_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_qa_findings'))
    )
    op.create_index(op.f('ix_qa_findings_run_id'), 'qa_findings', ['run_id'], unique=False)
    op.create_index('ix_qa_findings_severity', 'qa_findings', ['severity'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_qa_findings_severity', table_name='qa_findings')
    op.drop_index(op.f('ix_qa_findings_run_id'), table_name='qa_findings')
    op.drop_table('qa_findings')
    op.drop_index(op.f('ix_it_tasks_run_id'), table_name='it_tasks')
    op.drop_table('it_tasks')
    op.drop_index(op.f('ix_it_artifacts_run_id'), table_name='it_artifacts')
    op.drop_table('it_artifacts')
    op.drop_index('ix_it_runs_project_created', table_name='it_runs')
    op.drop_table('it_runs')
    op.drop_table('projects')
