import logging
from sqlalchemy import inspect, text
from src.db.connection import Base, get_engine, load_config

logger = logging.getLogger(__name__)


def _is_sqlite(engine) -> bool:
    return "sqlite" in str(engine.url)


def ensure_schema(engine=None, config: dict | None = None):
    if engine is None:
        engine = get_engine(config)
    if config is None:
        config = load_config()

    if _is_sqlite(engine):
        return

    schema = config["database"].get("schema", "public")
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.commit()
    logger.info(f"Schema '{schema}' ready")


def run_migrations(engine=None):
    if engine is None:
        engine = get_engine()

    ensure_schema(engine)
    Base.metadata.create_all(engine)
    logger.info("Migrations applied — all tables ready")


def table_exists(engine, table_name: str) -> bool:
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def create_dynamic_table(engine, table_name: str, columns: list[dict]):
    from sqlalchemy import Table, Column as SAColumn, MetaData, DateTime, Float, Integer, String, Text

    metadata = MetaData()
    existing = [c["name"] for c in inspect(engine).get_columns(table_name)] if table_exists(engine, table_name) else []

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
            new_cols.append(SAColumn(col["name"], col_type, nullable=True))

    if new_cols:
        table = Table(table_name, metadata, *new_cols)
        with engine.begin() as conn:
            metadata.create_all(conn)
        logger.info(f"Added {len(new_cols)} columns to '{table_name}'")
