from logging.config import fileConfig
from sqlalchemy import create_engine, pool
from alembic import context
from main import metadata

config = context.config
fileConfig(config.config_file_name)
target_metadata = metadata

def run_migrations_online():
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()