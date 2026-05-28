import logging
import threading
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import inspect, text
import pandas as pd

from src.db.connection import get_engine, get_session, load_config

logger = logging.getLogger(__name__)

api_app = FastAPI(title="RealView API", version="1.0", docs_url="/api/docs")

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TableInfo(BaseModel):
    name: str
    columns: list[dict]
    row_count: int


class DataResponse(BaseModel):
    table: str
    columns: list[str]
    rows: list[dict]
    total: int
    page: int
    page_size: int


_engine = None
_config = None


def set_api_engine(engine, config: dict):
    global _engine, _config
    _engine = engine
    _config = config


def get_api_engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def _get_qualified(table: str) -> str:
    schema = (_config or {}).get("database", {}).get("schema", "public")
    is_pg = "postgresql" in str(get_api_engine().url)
    return table if not is_pg else f"{schema}.{table}"


@api_app.get("/api/health")
def health():
    try:
        eng = get_api_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        backend = str(eng.url).split("://")[0]
        return {"status": "ok", "backend": backend}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@api_app.get("/api/stats")
def stats():
    session = get_session(get_api_engine())
    try:
        from src.db.models import ETLJob
        total = session.query(ETLJob).count()
        success = session.query(ETLJob).filter(ETLJob.status == "success").count()
        failed = session.query(ETLJob).filter(ETLJob.status == "failed").count()
        rows = session.query(ETLJob.rows_loaded).filter(ETLJob.status == "success").all()
        total_rows = sum(r[0] or 0 for r in rows)
        return {
            "total_jobs": total,
            "success": success,
            "failed": failed,
            "total_rows_loaded": total_rows,
        }
    finally:
        session.close()


@api_app.get("/api/tables")
def list_tables():
    insp = inspect(get_api_engine())
    tables = []
    for tname in insp.get_table_names():
        try:
            q = _get_qualified(tname)
            count = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {q}", get_api_engine()).iloc[0]["cnt"]
        except Exception:
            count = 0
        cols = [{"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(tname)]
        tables.append({"name": tname, "columns": cols, "row_count": int(count)})
    return tables


@api_app.get("/api/tables/{table_name}/columns")
def table_columns(table_name: str):
    insp = inspect(get_api_engine())
    if table_name not in insp.get_table_names():
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")
    return [{"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]} for c in insp.get_columns(table_name)]


@api_app.get("/api/tables/{table_name}/data")
def table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=10000),
    sort: Optional[str] = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    search: Optional[str] = None,
):
    insp = inspect(get_api_engine())
    if table_name not in insp.get_table_names():
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    q = _get_qualified(table_name)
    columns = [c["name"] for c in insp.get_columns(table_name)]
    col_str = ", ".join(f'"{c}"' for c in columns)

    where = ""
    if search:
        is_pg = "postgresql" in str(get_api_engine().url)
        search_clauses = [f'CAST("{c}" AS TEXT) LIKE :search' for c in columns]
        where = "WHERE " + " OR ".join(search_clauses)

    order_clause = ""
    if sort and sort in columns:
        order_clause = f'ORDER BY "{sort}" {order.upper()}'

    offset = (page - 1) * page_size
    limit_clause = f"LIMIT {page_size} OFFSET {offset}"

    count_sql = f"SELECT COUNT(*) as cnt FROM {q} {where}"
    data_sql = f"SELECT {col_str} FROM {q} {where} {order_clause} {limit_clause}"

    engine = get_api_engine()
    with engine.connect() as conn:
        total = conn.execute(text(count_sql), {"search": f"%{search}%"} if search else {}).scalar()
        result = conn.execute(text(data_sql), {"search": f"%{search}%"} if search else {})
        rows = [dict(zip(columns, row)) for row in result.fetchall()]

    sanitized = []
    for row in rows:
        sanitized.append({k: (str(v) if v is not None else None) for k, v in row.items()})

    return {
        "table": table_name,
        "columns": columns,
        "rows": sanitized,
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def start_api_server(engine, config: dict, host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    set_api_engine(engine, config)
    logger.info(f"API server starting on {host}:{port}")

    def run():
        uvicorn.run(api_app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
