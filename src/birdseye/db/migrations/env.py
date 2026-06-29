from logging.config import fileConfig

from alembic import context  # type: ignore[attr-defined]
from sqlalchemy import engine_from_config, pool

from birdseye.db.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_object(object, name, type_, reflected, compare_to):
    """
    Exclude PostGIS Tiger and Topology tables from autogenerate.
    Prevents Alembic from trying to drop extension-owned tables.
    """
    if type_ == "table":
        # Ignore entire tiger and topology schemas
        if getattr(object, "schema", None) in ("tiger", "topology"):
            return False

        # Common PostGIS Tiger / extension tables that live in public
        postgis_tables = {
            "spatial_ref_sys",
            "geocode_settings",
            "geocode_settings_default",
            "loader_platform",
            "loader_variables",
            "loader_lookuptables",
            "pagc_gaz",
            "pagc_lex",
            "pagc_rules",
            "featnames",
            "addrfeat",
            "addr",  # ← was missing
            "state",
            "county",
            "county_lookup",
            "countysub_lookup",
            "cousub",  # ← was missing
            "place",
            "place_lookup",
            "zip_lookup",
            "zip_lookup_base",
            "zip_lookup_all",
            "zip_state",
            "zip_state_loc",
            "street_type_lookup",
            "direction_lookup",
            "secondary_unit_lookup",
            "faces",  # ← was missing
            "edges",  # ← was missing
            "bg",
            "tract",
            "tabblock",
            "tabblock20",
            "zcta5",
            "layer",
            "topology",
        }
        if name in postgis_tables:
            return False

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_schemas=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
