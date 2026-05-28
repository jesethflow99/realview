import logging
import shutil
import tempfile
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.etl.pipeline import run_pipeline
from src.db.connection import get_engine, get_session, load_config

logger = logging.getLogger(__name__)


def _copy_to_temp_for_read(filepath: str) -> str:
    fp = Path(filepath)
    tmp = Path(tempfile.gettempdir()) / f"_realview_{fp.name}"
    shutil.copy2(filepath, tmp)
    return str(tmp)


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
        if src_path.name.startswith(".") or src_path.name.startswith("~$"):
            return
        self._process(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        dest_path = Path(event.dest_path)
        if dest_path.name.startswith(".") or dest_path.name.startswith("~$"):
            return
        if dest_path.suffix.lower() in (".csv", ".xlsx", ".xls", ".json", ".parquet", ".tsv", ".txt"):
            self._process(event.dest_path)

    def _process(self, filepath: str):
        path = Path(filepath)
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls", ".json", ".parquet", ".tsv", ".txt"):
            return
        now = time.time()
        if path.name in self._recent and now - self._recent[path.name] < 5:
            return
        self._recent[path.name] = now
        logger.info(f"Watcher detected: {path.name}")

        source = filepath
        for attempt in range(3):
            try:
                run_pipeline(source, engine=self.engine, session=self.session, config=self.config)
                break
            except (PermissionError, OSError) as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                try:
                    tmp = _copy_to_temp_for_read(filepath)
                    run_pipeline(tmp, engine=self.engine, session=self.session, config=self.config)
                except Exception as e2:
                    logger.warning(f"Could not read locked file {path.name}: {e2}")
            except Exception as e:
                logger.error(f"Pipeline failed for {path.name}: {e}")
                break


def start_watcher(config: dict, engine=None):
    input_dir = config["paths"]["input_dir"]
    Path(input_dir).mkdir(parents=True, exist_ok=True)
    if engine is None:
        engine = get_engine(config)
    event_handler = DataFileHandler(engine, config)
    observer = Observer()
    observer.schedule(event_handler, input_dir, recursive=False)
    observer.start()
    logger.info(f"Watcher started on {input_dir}")
    return observer
