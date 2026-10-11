"""Add private file locations, versioned passages, and indexed pgvector search."""
from alembic import op
import sqlalchemy as sa

revision = '003_knowledge'
down_revision = '002_documents'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('uploaded_documents')}
    if 'storage_backend' not in columns:
        op.add_column('uploaded_documents', sa.Column('storage_backend', sa.String(20), nullable=False, server_default='local'))
    if 'object_key' not in columns:
        op.add_column('uploaded_documents', sa.Column('object_key', sa.String(100), nullable=True))
    if bind.dialect.name == 'postgresql':
        # Supabase provides this extension. A self-hosted server needs pgvector
        # installed first; connection errors never cause a SQLite fallback.
        bind.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS extensions')
        bind.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions')
    from app.storage.knowledge import KnowledgeSource, KnowledgeChunk
    KnowledgeSource.__table__.create(bind, checkfirst=True)
    KnowledgeChunk.__table__.create(bind, checkfirst=True)
    for name, table, columns in (
        ('ix_jobs_claim', 'service_jobs', ['status', 'created_at', 'id']),
        ('ix_recent_runs', 'run_metadata', ['created_at', 'run_id']),
        ('ix_document_history', 'uploaded_documents', ['created_at', 'id']),
        ('ix_run_event_history', 'workflow_events', ['run_id', 'timestamp', 'id']),
        ('ix_knowledge_history', 'knowledge_sources', ['updated_at', 'id']),
    ):
        op.create_index(name, table, columns)
    if bind.dialect.name == 'postgresql':
        bind.exec_driver_sql('CREATE INDEX ix_knowledge_vector ON knowledge_chunks USING hnsw (embedding extensions.vector_cosine_ops)')
        bind.exec_driver_sql("CREATE INDEX ix_knowledge_keywords ON knowledge_chunks USING gin (to_tsvector('english', content))")


def downgrade():
    raise RuntimeError('Restore a backup instead of discarding saved knowledge.')
