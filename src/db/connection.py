import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

if sys.version_info >= (3, 11):
    import tomllib as toml_parser
else:
    import tomli as toml_parser

_config = None


def load_config(path: str = "config/settings.toml") -> dict:
    global _config
    if _config is None:
        if getattr(sys, "frozen", False):
            bundled = Path(sys._MEIPASS) / path
            if bundled.exists():
                path = str(bundled)
        for enc in ["utf-8", "cp1252", "latin-1"]:
            try:
                with open(path, "r", encoding=enc) as f:
                    _config = toml_parser.loads(f.read())
                break
            except (UnicodeDecodeError, ValueError):
                continue
    return _config


def get_database_url(config: dict | None = None) -> str:
    if config is None:
        config = load_config()
    db = config["database"]
    backend = db.get("backend", "sqlite")

    if backend == "sqlite":
        path = db.get("sqlite_path", "data/realview.db")
        return f"sqlite:///{path}"

    if backend in ("mariadb", "mysql"):
        return f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"

    return f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"


def get_engine(config: dict | None = None):
    if config is None:
        config = load_config()
    url = get_database_url(config)
    is_sqlite = url.startswith("sqlite")
    kwargs = {}
    if not is_sqlite:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 5
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


Base = declarative_base()
