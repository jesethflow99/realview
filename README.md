# RealView

ETL + Data Platform — transforma archivos CSV/Excel/JSON → PostgreSQL → Power BI (DirectQuery).

## Requisitos

- Python 3.10+
- Tkinter (incluido en Windows, en Linux: `sudo apt install python3-tk`)

## Instalación

```bash
git clone <repo>
cd realview
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
# Interfaz gráfica
python -m src.main desktop

# ETL manual
python -m src.main etl -f data/input/archivo.csv

# Daemon (watcher + scheduler)
python -m src.main daemon

# Solo migraciones
python -m src.main migrate
```

## Build ejecutable

```bash
# Windows
build.bat

# Linux/Mac
./build.sh
```

El ejecutable incluye PostgreSQL portátil embebido (se auto-descarga la primera vez).

## Power BI

Conecta Power BI Desktop a `localhost:5432`, base de datos `realview`, modo **DirectQuery**.
Usa las vistas `v_shipments_flat`, `v_shipments_monthly`, `v_top_clients`.

## Configuración

Edita `config/settings.toml`:

- `backend`: `sqlite` (dev), `postgresql` (servidor externo), `embedded` (portátil)
- `scheduler.interval_minutes`: cada cuánto revisa archivos nuevos
- `datasets`: mapeo de patrones de archivo → tablas
