"""
Download portable PostgreSQL for embedding.
Run once before building the executable.

Usage:
    python download_pg.py              # Downloads to ./pg/
    python download_pg.py --dir ./pg   # Custom directory
"""

import argparse
import sys
from pathlib import Path

from src.db.postgres_embedded import EmbeddedPostgres, PG_VERSION


def main():
    parser = argparse.ArgumentParser(description="Download portable PostgreSQL")
    parser.add_argument("--dir", default=".", help="Directory to download into")
    args = parser.parse_args()

    target = Path(args.dir).resolve()
    pg = EmbeddedPostgres(target)

    if pg.is_available:
        print(f"✅ PostgreSQL {PG_VERSION} ya está en {pg.bin_dir}")
        return

    print(f"📥 Descargando PostgreSQL {PG_VERSION} portátil...")
    pg.download()

    if pg.is_available:
        print(f"✅ PostgreSQL {PG_VERSION} descargado en {pg.pg_dir}")
        print(f"   Binarios: {pg.bin_dir}")
    else:
        print("❌ Error: No se pudo descargar PostgreSQL")
        sys.exit(1)


if __name__ == "__main__":
    main()
