"""Adopt the original tables and add durable service/connector records."""
from alembic import op
from app.storage.models import Base
from app.storage import control  # Register the new tables with the metadata.

revision = '001_connected_service'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # create_all adopts the seven original tables without altering/deleting
    # their contents. Later column changes must use a new explicit migration.
    bind = op.get_bind()
    # Freeze this historical revision: importing a later model must not create
    # its table before the migration that installs its required extensions.
    names = ('contacts', 'relationship_memory', 'interactions', 'external_actions',
             'outreach_runs', 'contact_action_locks', 'workflow_events', 'service_values',
             'run_metadata', 'service_jobs', 'telegram_updates', 'telegram_outbox')
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[name] for name in names])
    from sqlalchemy import select, insert
    from app.storage.models import RunRow, TraceRow, ActionRow
    from app.storage.control import RunMeta
    from sqlalchemy import func
    reply_ids = {row.get("reply_state", {}).get("run_id") for row in bind.execute(select(ActionRow.payload).where(ActionRow.kind == "reply")).scalars()}
    for run_id in bind.execute(select(RunRow.id)).scalars():
        if bind.execute(select(RunMeta.run_id).where(RunMeta.run_id == run_id)).first(): continue
        timestamp = bind.execute(select(func.min(TraceRow.timestamp)).where(TraceRow.run_id == run_id)).scalar() or ""
        bind.execute(insert(RunMeta).values(run_id=run_id, kind="reply" if run_id in reply_ids else "outreach",
            origin="legacy", created_at=timestamp, updated_at=timestamp, cancel_requested=False, browser_calls=0))


def downgrade():
    raise RuntimeError('Downgrade would discard application records; restore a backup instead.')
