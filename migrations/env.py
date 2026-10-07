from alembic import context

# The application supplies an already-open connection. Credentials never
# become command arguments or log output.
context.configure(connection=context.config.attributes['connection'])
with context.begin_transaction():
    context.run_migrations()
