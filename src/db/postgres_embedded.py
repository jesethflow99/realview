import atexit
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

PG_VERSION = "16.3"

# Detect architecture
IS_64BIT = sys.maxsize > 2**32

PG_DOWNLOADS = {
    "Windows": {
        "url": f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-1-windows-x64-binaries.zip",
        "zip": f"postgresql-{PG_VERSION}-1-windows-x64-binaries.zip",
        "extract_subdir": f"pgsql",
        "bin_relative": "bin",
    },
    "Linux": {
        "url": f"https://get.enterprisedb.com/postgresql/postgresql-{PG_VERSION}-1-linux-x64-binaries.tar.gz",
        "zip": f"postgresql-{PG_VERSION}-1-linux-x64-binaries.tar.gz",
        "extract_subdir": f"pgsql",
        "bin_relative": "bin",
    },
}


def _get_platform() -> str:
    if platform.system() == "Windows":
        return "Windows"
    return "Linux"


class EmbeddedPostgres:
    def __init__(self, app_dir: str | Path, port: int = 5432):
        self.app_dir = Path(app_dir)
        self.port = port
        self.platform = _get_platform()
        self.pg_dir = self.app_dir / "pg"
        self.data_dir = self.app_dir / "pgdata"
        self.db_name = "realview"
        self.db_user = "postgres"
        self.db_pass = "postgres"
        self._process = None

    @property
    def bin_dir(self) -> Path:
        dl = PG_DOWNLOADS.get(self.platform)
        return self.pg_dir / dl["extract_subdir"] / dl["bin_relative"]

    @property
    def pg_ctl(self) -> str:
        exe = "pg_ctl.exe" if self.platform == "Windows" else "pg_ctl"
        return str(self.bin_dir / exe)

    @property
    def initdb(self) -> str:
        exe = "initdb.exe" if self.platform == "Windows" else "initdb"
        return str(self.bin_dir / exe)

    @property
    def psql(self) -> str:
        exe = "psql.exe" if self.platform == "Windows" else "psql"
        return str(self.bin_dir / exe)

    @property
    def createdb(self) -> str:
        exe = "createdb.exe" if self.platform == "Windows" else "createdb"
        return str(self.bin_dir / exe)

    @property
    def pg_isready(self) -> str:
        exe = "pg_isready.exe" if self.platform == "Windows" else "pg_isready"
        return str(self.bin_dir / exe)

    @property
    def is_available(self) -> bool:
        return self.bin_dir.exists()

    def get_connection_url(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_pass}@localhost:{self.port}/{self.db_name}"

    def download(self, progress_callback=None):
        dl = PG_DOWNLOADS[self.platform]
        url = dl["url"]
        zip_name = dl["zip"]
        dest = self.app_dir / zip_name

        self.app_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading PostgreSQL {PG_VERSION} ({self.platform})...")
        print(f"Downloading PostgreSQL {PG_VERSION}... (~130MB)")

        def report(block, blocksize, totalsize):
            if progress_callback and totalsize > 0:
                pct = block * blocksize * 100 / totalsize
                progress_callback(min(pct, 99.9))

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/octet-stream,application/zip,*/*",
                "Referer": "https://www.enterprisedb.com/download-postgresql-binaries",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                with open(dest, "wb") as f:
                    total = int(response.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 65536
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded * 100 / total)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            raise RuntimeError(
                f"Failed to download PostgreSQL. Error: {e}\n"
                f"Download manually from:\n  "
                f"https://www.enterprisedb.com/download-postgresql-binaries\n"
                f"Or install PostgreSQL normally and set backend='postgresql' in config."
            )

        logger.info(f"Extracting to {self.pg_dir}...")
        print("Extracting...")
        if zip_name.endswith(".zip"):
            with zipfile.ZipFile(dest, "r") as zf:
                zf.extractall(self.pg_dir)
        else:
            import tarfile
            with tarfile.open(dest, "r:gz") as tf:
                tf.extractall(self.pg_dir)

        dest.unlink()
        logger.info(f"PostgreSQL extracted to {self.pg_dir}")
        return True

    def init_data_dir(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")

        logger.info(f"Initializing data directory: {self.data_dir}")
        result = subprocess.run(
            [self.initdb, "-D", str(self.data_dir), "--username", self.db_user, "--no-locale", "--encoding", "UTF8"],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if "already" in result.stderr.lower():
                logger.info("Data directory already initialized")
                return
            raise RuntimeError(f"initdb failed: {result.stderr}")

        logger.info("Data directory initialized")

        self._configure_pg_hba()

    def _configure_pg_hba(self):
        pg_hba = self.data_dir / "pg_hba.conf"
        if not pg_hba.exists():
            return
        content = pg_hba.read_text()
        # Allow password auth for local connections
        content = content.replace(
            "local   all             all                                     peer",
            "local   all             all                                     md5",
        )
        content = content.replace(
            "host    all             all             127.0.0.1/32            scram-sha-256",
            "host    all             all             127.0.0.1/32            md5",
        )
        pg_hba.write_text(content)

    def start(self) -> bool:
        if not self.is_available:
            raise RuntimeError("PostgreSQL not found. Call download() first.")

        if self._is_running():
            logger.info(f"PostgreSQL already running on port {self.port}")
            self._create_db_if_needed()
            return True

        if not self.data_dir.exists() or not list(self.data_dir.iterdir()):
            self.init_data_dir()

        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")

        logfile = self.app_dir / "pg.log"
        logger.info(f"Starting PostgreSQL on port {self.port}...")

        result = subprocess.run(
            [
                self.pg_ctl, "start",
                "-D", str(self.data_dir),
                "-l", str(logfile),
                "-o", f"-p {self.port}",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            if "already running" in result.stderr.lower() or "server is running" in result.stderr.lower():
                logger.info("PostgreSQL is already running")
                self._create_db_if_needed()
                return True
            raise RuntimeError(f"Failed to start PostgreSQL: {result.stderr}")

        atexit.register(self.stop)

        self._wait_ready(timeout=15)
        self._create_db_if_needed()
        return True

    def _wait_ready(self, timeout: int = 15):
        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")

        for i in range(timeout):
            result = subprocess.run(
                [self.pg_isready, "-q", "-h", "localhost", "-p", str(self.port)],
                env=env,
                capture_output=True,
            )
            if result.returncode == 0:
                logger.info("PostgreSQL is ready")
                return
            time.sleep(1)
        raise TimeoutError(f"PostgreSQL did not become ready in {timeout}s")

    def _is_running(self) -> bool:
        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")
        result = subprocess.run(
            [self.pg_isready, "-q", "-h", "localhost", "-p", str(self.port)],
            env=env,
            capture_output=True,
        )
        return result.returncode == 0

    def _create_db_if_needed(self):
        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")
        env["PGPASSWORD"] = self.db_pass

        result = subprocess.run(
            [
                self.psql, "-h", "localhost", "-p", str(self.port),
                "-U", self.db_user, "-d", "postgres",
                "-c", f"SELECT 1 FROM pg_database WHERE datname='{self.db_name}'",
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        if "1 row" not in result.stdout:
            logger.info(f"Creating database: {self.db_name}")
            subprocess.run(
                [self.createdb, "-h", "localhost", "-p", str(self.port), "-U", self.db_user, self.db_name],
                env=env,
                capture_output=True,
            )

    def stop(self):
        if self._process:
            self._process.terminate()
            self._process = None

        env = os.environ.copy()
        if self.platform == "Windows":
            env["PATH"] = str(self.bin_dir) + ";" + env.get("PATH", "")

        result = subprocess.run(
            [self.pg_ctl, "stop", "-D", str(self.data_dir), "-m", "fast"],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("PostgreSQL stopped")
        else:
            logger.warning(f"pg_ctl stop: {result.stderr}")

    @property
    def is_initialized(self) -> bool:
        return self.data_dir.exists() and (self.data_dir / "PG_VERSION").exists()
