"""Add owner uploads without changing existing runs or connector credentials."""
from alembic import op
from app.storage.documents import DocumentRow

revision = '002_documents'
down_revision = '001_connected_service'
branch_labels = None
depends_on = None


def upgrade():
    DocumentRow.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError('Document deletion requires a deliberate backup/retention decision.')
