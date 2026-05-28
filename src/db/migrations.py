import logging
from sqlalchemy import inspect, text
from src.db.connection import Base, get_engine, load_config

logger = logging.getLogger(__name__)


def _is_sqlite(engine) -> bool:
    return "sqlite" in str(engine.url)


def ensure_schema(engine=None, config: dict | None = None):
    if engine is None:
        engine = get_engine(config)
    if _is_sqlite(engine):
        return
    if "mysql" in str(engine.url) or "mariadb" in str(engine.url):
        return

    if config is None:
        config = load_config()
    schema = config["database"].get("schema", "public")
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.commit()
    logger.info(f"Schema '{schema}' ready")


def run_migrations(engine=None, config=None):
    if engine is None:
        engine = get_engine(config)

    ensure_schema(engine, config)
    Base.metadata.create_all(engine)
    logger.info("Migrations applied — all tables ready")


def table_exists(engine, table_name: str) -> bool:
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def create_dynamic_table(engine, table_name: str, columns: list[dict]):
    from sqlalchemy import Table, Column as SAColumn, MetaData, DateTime, Float, Integer, String, Text, UniqueConstraint
    from sqlalchemy.dialects.postgresql import JSONB

    metadata = MetaData()
    inspector = inspect(engine)
    existing = [c["name"] for c in inspector.get_columns(table_name)] if table_exists(engine, table_name) else []
    existing_pks = inspector.get_pk_constraint(table_name).get("constrained_columns", []) if table_exists(engine, table_name) else []

    new_cols = []
    for col in columns:
        if col["name"] not in existing:
            type_map = {
                "string": String(500),
                "text": Text,
                "integer": Integer,
                "float": Float,
                "datetime": DateTime(timezone=True),
            }
            col_type = type_map.get(col.get("type", "string"), String(500))
            nullable = col.get("nullable", True)
            new_cols.append(SAColumn(col["name"], col_type, nullable=nullable))

    if new_cols:
        table = Table(table_name, metadata, *new_cols)
        with engine.begin() as conn:
            metadata.create_all(conn)
        logger.info(f"Added {len(new_cols)} columns to '{table_name}'")

    if not existing_pks and not table_exists(engine, table_name):
        id_cols = [c["name"] for c in columns if c["name"].endswith("_id") or c["name"] == "id"]
        if id_cols:
            pk_col = id_cols[0]
            engine.execute(text(f"ALTER TABLE {table_name} ADD PRIMARY KEY ({pk_col})"))
