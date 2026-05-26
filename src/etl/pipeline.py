import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.db.connection import get_engine, load_config
from src.db.models import ETLJob
from src.db.migrations import table_exists
from src.etl.extract import extract
from src.etl.transform import transform
from src.etl.load import load

logger = logging.getLogger(__name__)


def compute_file_hash(filepath: str | Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_already_processed(engine, file_hash: str, session) -> bool:
    from sqlalchemy import select
    result = session.execute(
        select(ETLJob).where(ETLJob.file_hash == file_hash, ETLJob.status == "success")
    ).scalar_one_or_none()
    return result is not None


def make_etl_config(filename: str, config: dict) -> dict | None:
    datasets = config.get("datasets", {})
    for name, ds in datasets.items():
        import fnmatch
        pattern = ds.get("file_pattern", "")
        if pattern and fnmatch.fnmatch(filename, pattern):
            return {
                "dataset": name,
                "table": ds.get("table", name),
                "delimiter": ds.get("delimiter", ","),
                "skip_rows": ds.get("skip_rows", 0),
                "sheet_name": ds.get("sheet_name", 0),
                "column_mapping": ds.get("column_mapping", None),
            }
    return None


def run_pipeline(
    filepath: str | Path,
    engine=None,
    session=None,
    config: dict | None = None,
    target_table: str | None = None,
    dataset_name: str | None = None,
) -> dict:
    if config is None:
        config = load_config()
    if engine is None:
        engine = get_engine(config)
    if session is None:
        from src.db.connection import get_session
        session = get_session(engine)

    filepath = Path(filepath)
    filename = filepath.name
    file_hash = compute_file_hash(filepath)

    etl_cfg = make_etl_config(filename, config)

    if target_table is None and etl_cfg:
        target_table = etl_cfg["table"]
    if target_table is None:
        target_table = filepath.stem.lower().replace(" ", "_")

    if dataset_name is None and etl_cfg:
        dataset_name = etl_cfg["dataset"]
    if dataset_name is None:
        dataset_name = filename

    existing_job = (
        session.query(ETLJob)
        .filter(ETLJob.file_hash == file_hash, ETLJob.status == "success")
        .first()
    )
    if existing_job and config.get("etl", {}).get("idempotent", True):
        logger.info(f"File {filename} already processed (hash: {file_hash[:12]}...), skipping")
        return {"status": "skipped", "reason": "already processed", "file": filename}

    job = ETLJob(
        filename=filename,
        dataset=dataset_name,
        status="running",
        file_hash=file_hash,
        started_at=datetime.now(timezone.utc),
    )
    session.add(job)
    session.commit()

    try:
        df = extract(filepath)
        job.rows_read = len(df)

        column_mapping = etl_cfg.get("column_mapping", None) if etl_cfg else None

        df = transform(df, column_mapping=column_mapping)

        if not table_exists(engine, target_table):
            logger.info(f"Table '{target_table}' doesn't exist yet, creating from data")
            df.head(0).to_sql(target_table, engine, if_exists="replace", index=False)

        rows_loaded = load(
            df,
            engine,
            table_name=target_table,
            idempotent=config.get("etl", {}).get("idempotent", True),
            batch_size=config.get("etl", {}).get("batch_size", 1000),
            schema=config["database"].get("schema", "public"),
        )
        job.rows_loaded = rows_loaded
        job.status = "success"
        job.finished_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(f"Pipeline completed for {filename}: {rows_loaded} rows loaded")
        return {"status": "success", "file": filename, "rows": rows_loaded}

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.now(timezone.utc)
        session.commit()
        logger.error(f"Pipeline failed for {filename}: {e}")
        return {"status": "failed", "file": filename, "error": str(e)}
