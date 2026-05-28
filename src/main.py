import argparse
import logging
import signal
import sys
from pathlib import Path

from src.db.connection import load_config, get_engine
from src.db.migrations import run_migrations
from src.scheduler.scheduler import start_scheduler
from src.watcher.file_watcher import start_watcher
from src.etl.pipeline import run_pipeline
from src.desktop import run_desktop

logger = logging.getLogger(__name__)


def setup_logging(config: dict):
    level = getattr(logging, config["logging"].get("level", "INFO").upper(), logging.INFO)
    log_file = config["logging"].get("file", "logs/realview.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_etl(args, config: dict):
    if args.file:
        result = run_pipeline(args.file, config=config)
        print(f"Result: {result}")
    elif args.dir:
        for fpath in sorted(Path(args.dir).iterdir()):
            if fpath.suffix.lower() in (".csv", ".xlsx", ".xls", ".json", ".parquet", ".tsv", ".txt"):
                result = run_pipeline(fpath, config=config)
                print(f"{fpath.name}: {result['status']}")


def run_daemon(config: dict):
    engine = get_engine(config)
    run_migrations(engine, config)
    observers = []
    scheduler = None

    if config["scheduler"].get("enabled", True):
        scheduler = start_scheduler(config)

    if config["watcher"].get("enabled", True):
        observer = start_watcher(config)
        observers.append(observer)

    if config.get("api", {}).get("enabled", True):
        try:
            from src.api.server import start_api_server
            host = config.get("api", {}).get("host", "0.0.0.0")
            port = config.get("api", {}).get("port", 8000)
            start_api_server(engine, config, host=host, port=port)
            logger.info(f"REST API on http://{host}:{port}/api/docs")
        except Exception as e:
            logger.warning(f"REST API no pudo iniciar: {e}")

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        for obs in observers:
            obs.stop()
        for obs in observers:
            obs.join()
        if scheduler:
            scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("RealView daemon running. Ctrl+C to stop.")
    for obs in observers:
        obs.join()


def main():
    config = load_config()
    setup_logging(config)

    parser = argparse.ArgumentParser(description="RealView — ETL + Data Platform")
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    subparsers.add_parser("daemon", help="Run watcher + scheduler + REST API")

    subparsers.add_parser("migrate", help="Run DB migrations")

    api_parser = subparsers.add_parser("api", help="Start REST API server only")
    api_parser.add_argument("--host", type=str, default="0.0.0.0", help="API host")
    api_parser.add_argument("--port", type=int, default=8000, help="API port")

    etl_parser = subparsers.add_parser("etl", help="Run ETL once")
    etl_parser.add_argument("--file", "-f", type=str, help="Single file to process")
    etl_parser.add_argument("--dir", "-d", type=str, help="Directory of files to process")

    subparsers.add_parser("desktop", help="Launch desktop GUI")

    subparsers.add_parser("ui", help="Launch Streamlit UI (legacy)")

    args = parser.parse_args()

    if args.command == "daemon":
        run_daemon(config)
    elif args.command == "migrate":
        run_migrations()
        print("Migrations complete.")
    elif args.command == "api":
        from src.api.server import start_api_server
        engine = get_engine(config)
        run_migrations(engine, config)
        print(f"REST API starting on http://{args.host}:{args.port}/api/docs")
        start_api_server(engine, config, host=args.host, port=args.port)
        import signal as sig
        sig.signal(sig.SIGINT, lambda *_: sys.exit(0))
        sig.signal(sig.SIGTERM, lambda *_: sys.exit(0))
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    elif args.command == "etl":
        run_etl(args, config)
    elif args.command == "desktop":
        run_desktop()
    elif args.command == "ui":
        from src.ui.app import run_ui
        run_ui(port=args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
