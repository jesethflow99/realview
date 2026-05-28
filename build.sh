#!/usr/bin/env bash
set -euo pipefail

echo "=== RealView — Build ==="

# 1. Virtual env
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 2. Install deps
pip install -U pip
pip install -r requirements.txt
pip install pyinstaller

# 3. Download portable PostgreSQL
echo ""
echo "=== Verifying portable PostgreSQL ==="
if [ ! -f pg/pgsql/bin/pg_ctl ]; then
    echo "Downloading portable PostgreSQL (~130MB)..."
    python download_pg.py
else
    echo "PostgreSQL found in pg/"
fi

# 4. Verify imports
python -c "from src.db.connection import load_config; from src.db.migrations import run_migrations; print('✅ Backend OK')"
python -c "import customtkinter; print(f'✅ CustomTkinter {customtkinter.__version__}')"

# 5. Build with PyInstaller
echo ""
echo "=== Building executable ==="
pyinstaller \
    --name "RealView" \
    --onefile \
    --windowed \
    --add-data "config/settings.toml:config" \
    --add-data "pg:pgsql" \
    --hidden-import sqlalchemy \
    --hidden-import sqlalchemy.dialects.sqlite \
    --hidden-import sqlalchemy.dialects.postgresql \
    --hidden-import pandas \
    --hidden-import openpyxl \
    --hidden-import tomli \
    --hidden-import customtkinter \
    --hidden-import PIL \
    --hidden-import PIL._tkinter_finder \
    --collect-submodules customtkinter \
    --collect-data customtkinter \
    --collect-all tkinter \
    src/desktop.py

echo ""
echo "✅ Build complete!"
echo "   Executable: dist/RealView"
echo ""
echo "   On first run:"
echo "     1. Initializes PostgreSQL in pgdata/"
echo "     2. Creates database 'realview'"
echo "     3. Opens desktop GUI"
echo ""
echo "   Power BI connects to: localhost:5432 / realview"
