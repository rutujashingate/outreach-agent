"""Private server-side Postgres storage, including Supabase's hosted database.

A schema is a named group of tables. Ours stays outside Supabase's public Data
API: Telegram and the dashboard continue to use the authenticated Python app.
"""

from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

SCHEMA = "outreach"
INSTANCE_LOCK = 734872091  # One worker/poller per database, across computers too.


def connection_urls(value: str) -> tuple[str, str]:
    """Return SQLAlchemy and psycopg URLs for the same database, without logging them."""
    try:
        url = make_url(value.strip())
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError
        if not url.host or not url.database or not url.username or url.port == 6543:
            raise ValueError
        query = dict(url.query)
        if set(query) - {"sslmode", "sslrootcert", "connect_timeout", "application_name"}:
            raise ValueError
        if any(not isinstance(item, str) for item in query.values()):
            raise ValueError
        query.setdefault("sslmode", "require")
        query.setdefault("connect_timeout", "10")
        if url.host not in {"localhost", "127.0.0.1", "::1"} and query["sslmode"] not in {"require", "verify-ca", "verify-full"}:
            raise ValueError
        sql_url = url.set(drivername="postgresql+psycopg", query=query)
        pg_url = sql_url.set(drivername="postgresql")
        return sql_url.render_as_string(hide_password=False), pg_url.render_as_string(hide_password=False)
    except (ValueError, TypeError, ArgumentError):
        raise ValueError("Use a PostgreSQL direct or session-pooler URL with SSL; transaction pooler port 6543 is unsupported.") from None


def prepare_connection(connection, _record):
    """Select our private schema before SQLAlchemy inspects the connection."""
    previous = connection.autocommit
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS outreach")
            cursor.execute("SET SESSION search_path TO outreach")
            cursor.execute("REVOKE ALL ON SCHEMA outreach FROM PUBLIC")
    finally:
        connection.autocommit = previous


def protect_tables(engine):
    """Deny Data API roles access and enable row-level protection on our tables.

The server connects as the table owner. No anonymous or logged-in browser role
gets a policy: all owner access goes through the existing authenticated API.
"""
    with engine.begin() as connection:
        roles = ["PUBLIC"] + [name for name in ("anon", "authenticated", "service_role")
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": name}).scalar()]
        # These identifiers come from a fixed list, not user/model input.
        for role in roles:
            connection.exec_driver_sql(f"REVOKE ALL ON SCHEMA outreach FROM {role}")
            connection.exec_driver_sql(f"REVOKE ALL ON ALL TABLES IN SCHEMA outreach FROM {role}")
            connection.exec_driver_sql(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA outreach FROM {role}")
            connection.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA outreach REVOKE ALL ON TABLES FROM {role}")
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=:schema"), {"schema": SCHEMA}).scalars()
        for name in tables:
            quoted = connection.dialect.identifier_preparer.quote_identifier(name)
            connection.exec_driver_sql(f"ALTER TABLE outreach.{quoted} ENABLE ROW LEVEL SECURITY")


@contextmanager
def database_instance_lock(engine):
    """Keep another host from recovering or running this service's saved jobs."""
    with engine.connect() as connection:
        acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": INSTANCE_LOCK}).scalar()
        connection.commit()
        if not acquired:
            raise RuntimeError("Another outreach service is using this PostgreSQL database.")
        try:
            yield
        finally:
            if not connection.invalidated:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": INSTANCE_LOCK})
                connection.commit()
