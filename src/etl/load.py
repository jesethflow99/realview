import pandas as pd
from sqlalchemy import text, inspect
import logging

logger = logging.getLogger(__name__)


def _get_primary_key_columns(engine, table_name: str) -> list[str]:
    inspector = inspect(engine)
    pk = inspector.get_pk_constraint(table_name)
    return pk.get("constrained_columns", [])


def _get_column_types(engine, table_name: str) -> dict:
    inspector = inspect(engine)
    return {c["name"]: c["type"] for c in inspector.get_columns(table_name)}


def _is_sqlite(engine) -> bool:
    return "sqlite" in str(engine.url)


def _qualify(table: str, schema: str | None, is_sqlite: bool) -> str:
    return table if is_sqlite else f"{schema}.{table}"


def load(
    df: pd.DataFrame,
    engine,
    table_name: str,
    idempotent: bool = True,
    batch_size: int = 1000,
    schema: str = "public",
) -> int:
    if df.empty:
        logger.warning(f"No data to load into {table_name}")
        return 0

    sqlite = _is_sqlite(engine)
    qualified = _qualify(table_name, schema, sqlite)

    pk_cols = _get_primary_key_columns(engine, table_name) if idempotent else []
    cols = _get_column_types(engine, table_name)
    target_cols = [c for c in df.columns if c in cols]

    if not target_cols:
        raise ValueError(f"No columns in DataFrame match table '{table_name}' columns: {list(cols.keys())}")

    df_to_load = df[target_cols].copy()

    if pk_cols and idempotent:
        rows_before = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {qualified}", engine).iloc[0]["cnt"]
        temp_table = f"_etl_temp_{table_name}"

        df_to_load.to_sql(temp_table, engine, if_exists="replace", index=False, method="multi")

        set_clause = ", ".join(
            f"{col} = excluded.{col}" for col in target_cols if col not in pk_cols
        )
        insert_cols = ", ".join(target_cols)
        conflict_cols = ", ".join(pk_cols)

        noop_col = target_cols[0]
        final_set = set_clause if set_clause else f"{noop_col} = excluded.{noop_col}"

        upsert_sql = text(f"""
            INSERT INTO {qualified} ({insert_cols})
            SELECT {insert_cols} FROM {temp_table}
            ON CONFLICT ({conflict_cols})
            DO UPDATE SET {final_set}
        """)
        with engine.begin() as conn:
            conn.execute(upsert_sql)
            conn.execute(text(f"DROP TABLE IF EXISTS {temp_table}"))

        rows_after = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {qualified}", engine).iloc[0]["cnt"]
        loaded = int(rows_after - rows_before)
        logger.info(f"Upserted {len(df_to_load)} rows into {table_name} ({loaded} new, {len(df_to_load) - loaded} updated)")
        return loaded
    else:
        df_to_load.to_sql(
            table_name,
            engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=batch_size,
        )
        logger.info(f"Appended {len(df_to_load)} rows to {table_name}")
        return int(len(df_to_load))
