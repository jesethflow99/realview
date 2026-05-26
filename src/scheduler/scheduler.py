import logging
from pathlib import Path
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.db.connection import get_engine, get_session, load_config
from src.etl.pipeline import run_pipeline
from src.db.migrations import run_migrations

logger = logging.getLogger(__name__)


def scheduled_etl(config: dict):
    input_dir = Path(config["paths"]["input_dir"])
    processed_dir = Path(config["paths"]["processed_dir"])
    engine = get_engine(config)
    session = get_session(engine)

    input_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*"))
    if not files:
        logger.debug("Scheduler: no files to process")
        return

    for fpath in files:
        if fpath.suffix.lower() not in (".csv", ".xlsx", ".xls", ".json"):
            continue
        logger.info(f"Scheduler processing: {fpath.name}")
        result = run_pipeline(fpath, engine=engine, session=session, config=config)
        if result["status"] == "success":
            dest = processed_dir / fpath.name
            dest = dest.with_stem(f"{fpath.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            fpath.rename(dest)
            logger.info(f"Moved {fpath.name} -> processed/")


def start_scheduler(config: dict):
    run_migrations()
    scheduler = BackgroundScheduler()
    interval = config["scheduler"].get("interval_minutes", 5)

    scheduler.add_job(
        scheduled_etl,
        trigger=IntervalTrigger(minutes=interval),
        args=[config],
        id="etl_scheduled",
        name=f"ETL every {interval} minutes",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — ETL every {interval} min")
    return scheduler
