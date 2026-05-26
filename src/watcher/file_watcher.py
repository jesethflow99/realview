import logging
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.etl.pipeline import run_pipeline
from src.db.connection import get_engine, get_session, load_config

logger = logging.getLogger(__name__)


class DataFileHandler(FileSystemEventHandler):
    def __init__(self, engine, config: dict):
        self.engine = engine
        self.config = config
        self.session = get_session(engine)
        self._recent = {}

    def on_created(self, event):
        if event.is_directory:
            return
        self._process(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        src_path = Path(event.src_path)
        if src_path.name.startswith("."):
            return
        self._process(event.src_path)

    def _process(self, filepath: str):
        path = Path(filepath)
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls", ".json"):
            return
        now = time.time()
        if path.name in self._recent and now - self._recent[path.name] < 5:
            return
        self._recent[path.name] = now
        logger.info(f"Watcher detected: {path.name}")
        run_pipeline(filepath, engine=self.engine, session=self.session, config=self.config)


def start_watcher(config: dict):
    input_dir = config["paths"]["input_dir"]
    Path(input_dir).mkdir(parents=True, exist_ok=True)
    engine = get_engine(config)
    event_handler = DataFileHandler(engine, config)
    observer = Observer()
    observer.schedule(event_handler, input_dir, recursive=False)
    observer.start()
    logger.info(f"Watcher started on {input_dir}")
    return observer
