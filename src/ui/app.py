import sys
import subprocess
from pathlib import Path

import streamlit as st
import pandas as pd

from src.db.connection import load_config, get_engine, get_session
from src.db.migrations import run_migrations
from src.db.models import ETLJob
from src.etl.pipeline import run_pipeline

st.set_page_config(
    page_title="RealView",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def run_ui(port: int = 8501):
    run_migrations()
    script = Path(__file__).resolve()
    cmd = [sys.executable, "-m", "streamlit", "run", str(script), "--server.port", str(port)]
    subprocess.run(cmd, check=True)


@st.cache_resource
def get_resources():
    config = load_config()
    engine = get_engine(config)
    return config, engine


def sidebar():
    with st.sidebar:
        st.title("📊 RealView")
        st.caption("ETL + Data Platform")
        st.divider()
        page = st.radio(
            "Navegación",
            ["Dashboard", "Subir archivo", "ETL Logs", "Configuración"],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("v1.0 • PostgreSQL + Streamlit")
    return page


def page_dashboard(config, engine):
    st.title("📈 Dashboard")
    col1, col2, col3, col4 = st.columns(4)

    try:
        total = pd.read_sql("SELECT COUNT(*) as c FROM etl_jobs", engine).iloc[0]["c"]
        success = pd.read_sql("SELECT COUNT(*) as c FROM etl_jobs WHERE status='success'", engine).iloc[0]["c"]
        failed = pd.read_sql("SELECT COUNT(*) as c FROM etl_jobs WHERE status='failed'", engine).iloc[0]["c"]
        running = pd.read_sql("SELECT COUNT(*) as c FROM etl_jobs WHERE status='running'", engine).iloc[0]["c"]
        total_rows = pd.read_sql("SELECT COALESCE(SUM(rows_loaded),0) as c FROM etl_jobs WHERE status='success'", engine).iloc[0]["c"]
    except Exception:
        total = success = failed = running = total_rows = 0

    col1.metric("Total Ejecuciones", total)
    col2.metric("Exitosas", success, delta=f"{(success/total*100 if total else 0):.0f}%")
    col3.metric("Fallidas", failed)
    col4.metric("Filas Cargadas", f"{total_rows:,}")

    st.divider()
    st.subheader("📋 Últimas ejecuciones")
    try:
        df = pd.read_sql(
            "SELECT filename, dataset, status, rows_loaded, error, started_at, finished_at "
            "FROM etl_jobs ORDER BY started_at DESC LIMIT 20",
            engine,
        )
        if not df.empty:
            df = df.fillna("")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay ejecuciones registradas todavía.")
    except Exception as e:
        st.error(f"Error al cargar logs: {e}")

    st.divider()
    st.subheader("📦 Tablas en la base de datos")
    try:
        tables = pd.read_sql(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')",
            engine,
        )
        st.dataframe(tables, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error al listar tablas: {e}")


def page_upload(config, engine):
    st.title("📤 Subir archivo")
    st.markdown("Sube un archivo **CSV**, **Excel** o **JSON** para procesarlo e insertarlo en la base de datos.")

    uploaded_file = st.file_uploader(
        "Selecciona un archivo",
        type=["csv", "xlsx", "xls", "json"],
    )

    if uploaded_file is not None:
        ext = Path(uploaded_file.name).suffix.lower()
        st.success(f"Archivo recibido: {uploaded_file.name}")

        with st.expander("🔍 Vista previa", expanded=True):
            try:
                if ext == ".csv":
                    preview = pd.read_csv(uploaded_file)
                elif ext in (".xlsx", ".xls"):
                    preview = pd.read_excel(uploaded_file)
                elif ext == ".json":
                    preview = pd.read_json(uploaded_file)
                else:
                    st.error("Formato no soportado")
                    return
                uploaded_file.seek(0)
                st.dataframe(preview.head(10), use_container_width=True)
                st.caption(f"{len(preview)} filas × {len(preview.columns)} columnas")
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")
                return

        col1, col2 = st.columns(2)
        with col1:
            target_table = st.text_input(
                "Nombre de la tabla destino",
                value=Path(uploaded_file.name).stem.lower().replace(" ", "_"),
            )
        with col2:
            dataset_name = st.text_input(
                "Nombre del dataset",
                value=Path(uploaded_file.name).stem,
            )

        if st.button("🚀 Procesar y cargar", type="primary", use_container_width=True):
            tmp = Path("/tmp") / uploaded_file.name
            tmp.write_bytes(uploaded_file.getbuffer())
            with st.spinner("Procesando..."):
                result = run_pipeline(
                    tmp,
                    engine=engine,
                    config=config,
                    target_table=target_table,
                    dataset_name=dataset_name,
                )
            tmp.unlink(missing_ok=True)

            if result["status"] == "success":
                st.success(f"✅ {result['rows']} filas cargadas exitosamente en `{target_table}`")
            elif result["status"] == "skipped":
                st.info(f"⏭️ Archivo ya procesado anteriormente: {result.get('reason', '')}")
            else:
                st.error(f"❌ Error: {result.get('error', 'desconocido')}")


def page_logs(config, engine):
    st.title("📋 ETL Logs")
    session = get_session(engine)

    col1, col2 = st.columns(2)
    with col1:
        status_filter = st.selectbox("Filtrar por estado", ["todos", "success", "failed", "running", "skipped"])
    with col2:
        limit = st.slider("Registros a mostrar", 10, 500, 50)

    query = session.query(ETLJob).order_by(ETLJob.started_at.desc())
    if status_filter != "todos":
        query = query.filter(ETLJob.status == status_filter)
    jobs = query.limit(limit).all()

    if not jobs:
        st.info("No hay registros.")
        return

    data = []
    for j in jobs:
        data.append({
            "ID": j.id,
            "Archivo": j.filename,
            "Dataset": j.dataset,
            "Estado": j.status,
            "Filas leídas": j.rows_read,
            "Filas cargadas": j.rows_loaded,
            "Error": (j.error or "")[:80],
            "Inicio": j.started_at,
            "Fin": j.finished_at,
        })
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📊 Resumen")
    summary = pd.read_sql(
        "SELECT status, COUNT(*) as count FROM etl_jobs GROUP BY status ORDER BY count DESC",
        engine,
    )
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.dataframe(summary, use_container_width=True, hide_index=True)
    with col_b:
        st.bar_chart(summary.set_index("status")["count"])


def page_config(config, engine):
    st.title("⚙️ Configuración")

    with st.expander("📁 Rutas", expanded=True):
        st.json(config.get("paths", {}))

    with st.expander("🗄️ Base de datos"):
        db = dict(config.get("database", {}))
        db["password"] = "********"
        st.json(db)

    with st.expander("⚡ ETL"):
        st.json(config.get("etl", {}))

    with st.expander("🕒 Scheduler"):
        st.json(config.get("scheduler", {}))

    with st.expander("👀 Watcher"):
        st.json(config.get("watcher", {}))

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Correr migraciones", use_container_width=True):
            with st.spinner("Migrando..."):
                run_migrations(engine)
            st.success("Migraciones completadas")
            st.rerun()
    with col2:
        st.page_link("sql/views.sql", label="📐 Ver vistas SQL", icon="🗄️")


def main():
    config, engine = get_resources()
    page = sidebar()

    if page == "Dashboard":
        page_dashboard(config, engine)
    elif page == "Subir archivo":
        page_upload(config, engine)
    elif page == "ETL Logs":
        page_logs(config, engine)
    elif page == "Configuración":
        page_config(config, engine)


if __name__ == "__main__":
    main()
