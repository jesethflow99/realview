import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
import pandas as pd

from src.db.connection import load_config, get_engine, get_session, get_database_url
from src.db.migrations import run_migrations
from src.db.models import ETLJob
from src.etl.pipeline import run_pipeline

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


def _detect_system_postgres() -> dict | None:
    candidates = []
    if sys.platform == "win32":
        pg_base = Path("C:/Program Files/PostgreSQL")
        if pg_base.exists():
            for ver_dir in sorted(pg_base.iterdir(), reverse=True):
                pg_isready = ver_dir / "bin" / "pg_isready.exe"
                if pg_isready.exists():
                    candidates.append(pg_isready)
    else:
        for path in ["/usr/bin/pg_isready", "/usr/local/bin/pg_isready"]:
            if Path(path).exists():
                candidates.append(Path(path))

    for cmd in candidates:
        try:
            result = subprocess.run(
                [str(cmd), "-q", "-h", "localhost", "-p", "5432"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return {"pg_isready": str(cmd)}
        except Exception:
            continue

    for cmd_name in ["pg_isready", "psql"]:
        try:
            result = subprocess.run(
                [cmd_name, "-q", "-h", "localhost", "-p", "5432"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return {"pg_isready": cmd_name}
        except Exception:
            continue

    return None


class RealViewApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("RealView — ETL & Data Platform")
        self.geometry("1200x750")
        self.minsize(900, 600)
        self._embedded_pg = None
        self._watcher_observer = None
        self._scheduler = None
        self.engine = None
        self.connected = False

        self.config_data = load_config()
        self._api_port = self.config_data.get("api", {}).get("port", 8000)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._setup_grid()
        self._build_sidebar()
        self._build_main_area()

        self._try_connect()

        self.show_frame("database" if not self.connected else "dashboard")

    def _update_status(self, connected: bool, backend: str = ""):
        self.connected = connected
        if connected:
            self.status_dot.configure(text_color="green")
            names = {"sqlite": "SQLite", "postgresql": "PostgreSQL", "embedded": "PG Embebido", "mariadb": "MariaDB", "mysql": "MySQL"}
            backend_label = names.get(backend, backend)
            self.status_label.configure(text=f"Conectado — {backend_label}")
        else:
            self.status_dot.configure(text_color="red")
            self.status_label.configure(text="Desconectado")

    def _try_connect(self, backend_override: str | None = None) -> bool:
        backend = backend_override or self.config_data["database"].get("backend", "sqlite")
        old_backend = self.config_data["database"].get("backend", "")

        if backend == "embedded":
            from src.db.postgres_embedded import EmbeddedPostgres
            app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
            port = self.config_data["database"].get("port", 5432)
            emb = EmbeddedPostgres(app_dir, port=port)
            if emb.is_available:
                try:
                    if self._embedded_pg:
                        self._embedded_pg.stop()
                    self._embedded_pg = emb
                    emb.start()
                    self.config_data["database"]["backend"] = "embedded"
                    self.config_data["database"]["host"] = "localhost"
                    self.config_data["database"]["port"] = port
                    self.config_data["database"]["name"] = emb.db_name
                    self.config_data["database"]["user"] = emb.db_user
                    self.config_data["database"]["password"] = emb.db_pass
                except Exception as e:
                    print(f"[ERROR] Embedded PG: {e}")
                    self._embedded_pg = None
                    self.engine = None
                    self._update_status(False)
                    return False

        self.config_data["database"]["backend"] = backend

        if backend_override and old_backend != backend_override:
            from src.db.connection import _config
            import src.db.connection as conn_module
            conn_module._config = None

        try:
            self.engine = get_engine(self.config_data)
            run_migrations(self.engine, self.config_data)
            backend_name = self.config_data["database"]["backend"]
            self._update_status(True, backend_name)
            self._start_watcher()
            self._start_scheduler()
            self._start_api()
            return True
        except Exception as e:
            print(f"[ERROR] Connection failed: {e}")
            self.engine = None
            self._update_status(False)
            return False

    def _start_watcher(self):
        if not self.engine:
            return
        if not self.config_data.get("watcher", {}).get("enabled", True):
            return
        if self._watcher_observer:
            return
        try:
            from src.watcher.file_watcher import start_watcher
            Path(self.config_data["paths"]["input_dir"]).mkdir(parents=True, exist_ok=True)
            self._watcher_observer = start_watcher(self.config_data, self.engine)
        except Exception as e:
            print(f"[WARN] Watcher no pudo iniciar: {e}")

    def _start_scheduler(self):
        if not self.engine:
            return
        if not self.config_data.get("scheduler", {}).get("enabled", True):
            return
        if self._scheduler:
            return
        try:
            from src.scheduler.scheduler import start_scheduler
            self._scheduler = start_scheduler(self.config_data, engine=self.engine)
        except Exception as e:
            print(f"[WARN] Scheduler no pudo iniciar: {e}")

    def _start_api(self):
        if not self.engine:
            return
        if not self.config_data.get("api", {}).get("enabled", True):
            print("[INFO] REST API disabled in config")
            return
        try:
            from src.api.server import start_api_server
            host = self.config_data.get("api", {}).get("host", "0.0.0.0")
            port = self.config_data.get("api", {}).get("port", 8000)
            start_api_server(self.engine, self.config_data, host=host, port=port)
            print(f"[INFO] REST API started on http://{host}:{port}/api/docs")
        except ImportError:
            print("[WARN] fastapi/uvicorn not installed. pip install fastapi uvicorn")
        except Exception as e:
            print(f"[WARN] REST API no pudo iniciar: {e}")

    def _setup_grid(self):
        self.grid_columnconfigure(0, weight=0, minsize=220)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1)

        logo = ctk.CTkLabel(self.sidebar, text="📊 RealView", font=ctk.CTkFont(size=22, weight="bold"))
        logo.grid(row=0, column=0, padx=20, pady=(25, 5))

        subtitle = ctk.CTkLabel(self.sidebar, text="ETL + Data Platform", font=ctk.CTkFont(size=12), text_color="gray")
        subtitle.grid(row=1, column=0, padx=20, pady=(0, 20))

        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "📈  Dashboard"),
            ("upload",    "📤  Subir archivo"),
            ("logs",      "📋  ETL Logs"),
            ("database",  "🔌  Base de datos"),
            ("settings",  "⚙️  Configuración"),
        ]

        for i, (key, label) in enumerate(nav_items):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=("gray75", "gray25"),
                text_color=("gray10", "gray90"),
                command=lambda k=key: self.show_frame(k),
            )
            btn.grid(row=i + 2, column=0, padx=10, pady=3, sticky="ew")
            self.nav_buttons[key] = btn

        status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_frame.grid(row=6, column=0, padx=15, pady=15, sticky="ew")
        self.status_dot = ctk.CTkLabel(status_frame, text="●", text_color="green", font=ctk.CTkFont(size=14))
        self.status_dot.pack(side="left")
        self.status_label = ctk.CTkLabel(status_frame, text="Conectado", font=ctk.CTkFont(size=11), text_color="gray")
        self.status_label.pack(side="left", padx=5)

        version = ctk.CTkLabel(self.sidebar, text="v1.0", font=ctk.CTkFont(size=10), text_color="gray")
        version.grid(row=7, column=0, pady=(0, 15))

    def _build_main_area(self):
        self.frames = {}
        for name in ("database", "dashboard", "upload", "logs", "settings"):
            frame = ctk.CTkFrame(self)
            self.frames[name] = frame
            frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)

    def show_frame(self, name):
        for f in self.frames.values():
            f.grid_remove()
        self.frames[name].grid()
        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.configure(fg_color=("gray80", "gray20"))
            else:
                btn.configure(fg_color="transparent")

        if name == "database":
            self._render_setup()
        elif name == "dashboard":
            self._render_dashboard()
        elif name == "upload":
            self._render_upload()
        elif name == "logs":
            self._render_logs()
        elif name == "settings":
            self._render_settings()

    def _clear_frame(self, frame):
        for w in frame.winfo_children():
            w.destroy()

    # ── SETUP (Database connection screen) ─────────
    def _render_setup(self):
        self._clear_frame(self.frames["database"])
        f = self.frames["database"]
        f.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(f, text="🔌 Base de Datos", font=ctk.CTkFont(size=22, weight="bold"))
        header.pack(pady=(40, 5))

        sub = ctk.CTkLabel(f, text="Selecciona el servidor donde se expondran los datos", font=ctk.CTkFont(size=13), text_color="gray")
        sub.pack(pady=(0, 30))

        card = ctk.CTkFrame(f, corner_radius=12, fg_color=("gray95", "gray17"))
        card.pack(padx=40, pady=5, fill="x")

        ctk.CTkLabel(card, text="Tipo de backend", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))

        self.backend_var = ctk.StringVar(value=self.config_data["database"].get("backend", "sqlite"))
        backend_menu = ctk.CTkOptionMenu(
            card,
            values=["sqlite", "postgresql", "mariadb", "mysql", "embedded"],
            variable=self.backend_var,
            command=self._on_backend_change,
        )
        backend_menu.pack(padx=20, pady=5, fill="x")

        self.backend_hint = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.backend_hint.pack(anchor="w", padx=20, pady=(2, 10))

        self._pg_fields = ctk.CTkFrame(card, fg_color="transparent")
        self._pg_fields.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(self._pg_fields, text="Host").grid(row=0, column=0, padx=20, pady=(5, 0), sticky="w")
        ctk.CTkLabel(self._pg_fields, text="Puerto").grid(row=0, column=1, padx=20, pady=(5, 0), sticky="w")
        self.pg_host_entry = ctk.CTkEntry(self._pg_fields, placeholder_text="localhost")
        self.pg_host_entry.grid(row=1, column=0, padx=20, pady=(2, 10), sticky="ew")
        self.pg_host_entry.insert(0, self.config_data["database"].get("host", "localhost"))
        self.pg_port_entry = ctk.CTkEntry(self._pg_fields, placeholder_text="5432", width=80)
        self.pg_port_entry.grid(row=1, column=1, padx=20, pady=(2, 10), sticky="w")
        self.pg_port_entry.insert(0, str(self.config_data["database"].get("port", 5432)))

        ctk.CTkLabel(self._pg_fields, text="Base de datos").grid(row=2, column=0, padx=20, pady=(5, 0), sticky="w")
        ctk.CTkLabel(self._pg_fields, text="Usuario").grid(row=2, column=1, padx=20, pady=(5, 0), sticky="w")
        self.pg_db_entry = ctk.CTkEntry(self._pg_fields, placeholder_text="realview")
        self.pg_db_entry.grid(row=3, column=0, padx=20, pady=(2, 10), sticky="ew")
        self.pg_db_entry.insert(0, self.config_data["database"].get("name", "realview"))
        self.pg_user_entry = ctk.CTkEntry(self._pg_fields, placeholder_text="postgres")
        self.pg_user_entry.grid(row=3, column=1, padx=20, pady=(2, 10), sticky="ew")
        self.pg_user_entry.insert(0, self.config_data["database"].get("user", "postgres"))

        ctk.CTkLabel(self._pg_fields, text="Contrasena").grid(row=4, column=0, padx=20, pady=(5, 0), sticky="w")
        self.pg_pass_entry = ctk.CTkEntry(self._pg_fields, placeholder_text="postgres", show="*")
        self.pg_pass_entry.grid(row=4, column=1, padx=20, pady=(2, 10), sticky="ew")
        self.pg_pass_entry.insert(0, self.config_data["database"].get("password", "postgres"))

        self._on_backend_change(self.backend_var.get())

        btn_frame = ctk.CTkFrame(f, fg_color="transparent")
        btn_frame.pack(padx=40, pady=(20, 10), fill="x")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.test_btn = ctk.CTkButton(btn_frame, text="🔍  Probar conexion", command=self._test_connection, height=40)
        self.test_btn.grid(row=0, column=0, padx=5)

        self.connect_btn = ctk.CTkButton(btn_frame, text="✅  Conectar y continuar", command=self._connect_and_go, height=40)
        self.connect_btn.grid(row=0, column=1, padx=5)

        self.setup_status = ctk.CTkLabel(f, text="", font=ctk.CTkFont(size=13))
        self.setup_status.pack(pady=(5, 40))

    def _on_backend_change(self, choice):
        hints = {
            "sqlite": "Archivo local data/realview.db — sin servidor externo. DirectQuery NO disponible.",
            "postgresql": "Servidor PostgreSQL externo. DirectQuery y REST API disponibles.",
            "mariadb": "Servidor MariaDB. REST API disponible. Puerto default: 3306.",
            "mysql": "Servidor MySQL. REST API disponible. Puerto default: 3306.",
            "embedded": "PostgreSQL portatil auto-gestionado (requiere binarios en pg/). DirectQuery y REST API disponibles.",
        }
        self.backend_hint.configure(text=hints.get(choice, ""))
        if choice == "sqlite":
            self._pg_fields.pack_forget()
        else:
            self._pg_fields.pack(padx=10, pady=5, fill="x")
            if choice in ("mariadb", "mysql"):
                self.pg_port_entry.delete(0, "end")
                self.pg_port_entry.insert(0, "3306")
            elif choice == "postgresql":
                self.pg_port_entry.delete(0, "end")
                self.pg_port_entry.insert(0, "5432")

    def _test_connection(self):
        self.test_btn.configure(state="disabled", text="⏳  Probando...")
        self.setup_status.configure(text="", text_color="gray")
        self.update()

        backend = self.backend_var.get()
        self.config_data["database"]["backend"] = backend
        if backend in ("postgresql", "embedded", "mariadb", "mysql"):
            self.config_data["database"]["host"] = self.pg_host_entry.get().strip() or "localhost"
            self.config_data["database"]["port"] = int(self.pg_port_entry.get().strip() or "5432")
            self.config_data["database"]["name"] = self.pg_db_entry.get().strip() or "realview"
            self.config_data["database"]["user"] = self.pg_user_entry.get().strip() or "postgres"
            self.config_data["database"]["password"] = self.pg_pass_entry.get().strip() or "postgres"

        def task():
            try:
                ok = self._try_connect()
                if ok:
                    self.after(0, lambda: self.setup_status.configure(
                        text="✅ Conexion exitosa!", text_color="green"))
                else:
                    self.after(0, lambda: self.setup_status.configure(
                        text="❌ No se pudo conectar. Revisa los datos.", text_color="red"))
            except Exception as e:
                self.after(0, lambda: self.setup_status.configure(
                    text=f"❌ Error: {str(e)[:100]}", text_color="red"))
            finally:
                self.after(0, lambda: self.test_btn.configure(state="normal", text="🔍  Probar conexion"))

        threading.Thread(target=task, daemon=True).start()

    def _connect_and_go(self):
        self.connect_btn.configure(state="disabled", text="⏳  Conectando...")
        self.update()

        backend = self.backend_var.get()
        if backend in ("postgresql", "embedded", "mariadb", "mysql"):
            self.config_data["database"]["host"] = self.pg_host_entry.get().strip() or "localhost"
            self.config_data["database"]["port"] = int(self.pg_port_entry.get().strip() or "5432")
            self.config_data["database"]["name"] = self.pg_db_entry.get().strip() or "realview"
            self.config_data["database"]["user"] = self.pg_user_entry.get().strip() or "postgres"
            self.config_data["database"]["password"] = self.pg_pass_entry.get().strip() or "postgres"

        def task():
            try:
                ok = self._try_connect()
                self.after(0, lambda: self._connect_result(ok))
            except Exception as e:
                self.after(0, lambda: self.setup_status.configure(
                    text=f"❌ Error: {str(e)[:100]}", text_color="red"))
                self.after(0, lambda: self.connect_btn.configure(state="normal", text="✅  Conectar y continuar"))

        threading.Thread(target=task, daemon=True).start()

    def _connect_result(self, ok):
        self.connect_btn.configure(state="normal", text="✅  Conectar y continuar")
        if ok:
            self._save_config_to_file()
            self.show_frame("dashboard")
        else:
            self.setup_status.configure(
                text="❌ No se pudo conectar. Revisa los datos o elige otro backend.", text_color="red")

    def _save_config_to_file(self):
        toml_path = Path("config/settings.toml")

        content = ""
        if toml_path.exists():
            for enc in ["utf-8", "cp1252", "latin-1"]:
                try:
                    content = toml_path.read_text(encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

        import re
        new_backend = self.config_data["database"].get("backend", "sqlite")
        if content:
            content = re.sub(
                r'^\s*backend\s*=\s*"[^"]*"',
                f'backend = "{new_backend}"',
                content,
                flags=re.MULTILINE,
            )
            if "host" in self.config_data["database"] and new_backend != "sqlite":
                db = self.config_data["database"]
                for key in ["host", "port", "name", "user", "password"]:
                    val = db.get(key, "")
                    pattern = rf'^\s*{key}\s*=\s*.*'
                    replacement = f'{key} = "{val}"' if key != "port" else f"port = {val}"
                    if re.search(pattern, content, flags=re.MULTILINE):
                        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            db = self.config_data["database"]
            lines = ["[database]", f"backend = \"{new_backend}\""]
            if new_backend != "sqlite":
                lines.append(f"host = \"{db.get('host', 'localhost')}\"")
                lines.append(f"port = {db.get('port', 5432)}")
                lines.append(f"name = \"{db.get('name', 'realview')}\"")
                lines.append(f"user = \"{db.get('user', 'postgres')}\"")
                lines.append(f"password = \"{db.get('password', 'postgres')}\"")
            lines.append(f"schema = \"{db.get('schema', 'public')}\"")
            lines.append(f"sqlite_path = \"{db.get('sqlite_path', 'data/realview.db')}\"")
            content = "\n".join(lines) + "\n"

        toml_path.parent.mkdir(exist_ok=True)
        toml_path.write_text(content, encoding="utf-8")

    def _render_dashboard(self):
        self._clear_frame(self.frames["dashboard"])
        f = self.frames["dashboard"]
        f.grid_columnconfigure((0, 1, 2, 3), weight=1)

        header = ctk.CTkLabel(f, text="📈 Dashboard", font=ctk.CTkFont(size=20, weight="bold"), anchor="w")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 15))

        stats = self._get_stats()
        metrics = [
            ("Total ejecuciones", str(stats["total"]), "#1f77b4"),
            ("Exitosas", str(stats["success"]), "#2ca02c"),
            ("Fallidas", str(stats["failed"]), "#d62728"),
            ("Filas cargadas", f"{stats['rows']:,}", "#ff7f0e"),
        ]
        for i, (label, value, color) in enumerate(metrics):
            card = ctk.CTkFrame(f, fg_color=("white", "gray17"), corner_radius=12)
            card.grid(row=1, column=i, padx=5, pady=5, sticky="nsew")
            card.grid_columnconfigure(0, weight=1)
            val = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=32, weight="bold"), text_color=color)
            val.grid(row=0, column=0, pady=(15, 0))
            lbl = ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=13), text_color="gray")
            lbl.grid(row=1, column=0, pady=(0, 15))

        # Recent runs table
        table_frame = ctk.CTkFrame(f)
        table_frame.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(20, 0))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(1, weight=1)

        table_header = ctk.CTkLabel(table_frame, text="Últimas ejecuciones", font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        table_header.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        cols = ("Archivo", "Estado", "Filas", "Error", "Inicio")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=10)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=120, minwidth=80)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        vsb.grid(row=1, column=1, sticky="ns", pady=(0, 10))
        table_frame.grid_rowconfigure(1, weight=1)

        try:
            session = get_session(self.engine)
            jobs = session.query(ETLJob).order_by(ETLJob.started_at.desc()).limit(50).all()
            for j in jobs:
                err = (j.error or "")[:50]
                inicio = j.started_at.strftime("%Y-%m-%d %H:%M") if j.started_at else ""
                tree.insert("", "end", values=(j.filename, j.status, j.rows_loaded, err, inicio))
            session.close()
        except Exception as e:
            tree.insert("", "end", values=("Error", str(e), "", "", ""))

        f.grid_rowconfigure(2, weight=1)

    def _get_stats(self):
        result = {"total": 0, "success": 0, "failed": 0, "rows": 0}
        try:
            session = get_session(self.engine)
            result["total"] = session.query(ETLJob).count()
            result["success"] = session.query(ETLJob).filter(ETLJob.status == "success").count()
            result["failed"] = session.query(ETLJob).filter(ETLJob.status == "failed").count()
            rows = session.query(ETLJob.rows_loaded).filter(ETLJob.status == "success").all()
            result["rows"] = sum(r[0] or 0 for r in rows)
            session.close()
        except Exception:
            pass
        return result

    # ── UPLOAD ─────────────────────────────────────

    def _render_upload(self):
        self._clear_frame(self.frames["upload"])
        f = self.frames["upload"]
        f.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(f, text="📤 Subir archivo", font=ctk.CTkFont(size=20, weight="bold"), anchor="w")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))

        self.upload_filepath = None
        self.upload_df = None

        btn_frame = ctk.CTkFrame(f, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=0)

        select_btn = ctk.CTkButton(btn_frame, text="📁  Seleccionar archivo", command=self._select_file, width=180)
        select_btn.grid(row=0, column=0, padx=(0, 10))

        self.file_label = ctk.CTkLabel(btn_frame, text="Ningún archivo seleccionado", text_color="gray")
        self.file_label.grid(row=0, column=1, sticky="w")

        # Preview
        preview_frame = ctk.CTkFrame(f)
        preview_frame.grid(row=2, column=0, sticky="nsew", pady=15)
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)
        preview_header = ctk.CTkLabel(preview_frame, text="Vista previa", font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        preview_header.grid(row=0, column=0, sticky="ew", padx=10, pady=10)

        self.preview_tree = ttk.Treeview(preview_frame, show="headings", height=8)
        self.preview_vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=self.preview_vsb.set)
        self.preview_tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview_vsb.grid(row=1, column=1, sticky="ns", pady=(0, 10))
        self.preview_info = ctk.CTkLabel(preview_frame, text="", text_color="gray")
        self.preview_info.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 5))

        # Load controls
        ctrl_frame = ctk.CTkFrame(f, fg_color="transparent")
        ctrl_frame.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ctrl_frame.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkLabel(ctrl_frame, text="Tabla destino:").grid(row=0, column=0, sticky="w")
        self.table_entry = ctk.CTkEntry(ctrl_frame, placeholder_text="nombre_tabla")
        self.table_entry.grid(row=0, column=1, sticky="ew", padx=5)

        self.load_btn = ctk.CTkButton(ctrl_frame, text="🚀  Cargar a DB", command=self._load_to_db, state="disabled")
        self.load_btn.grid(row=0, column=2, sticky="e")

        self.load_status = ctk.CTkLabel(f, text="", text_color="gray")
        self.load_status.grid(row=4, column=0, sticky="w", pady=(5, 0))

        f.grid_rowconfigure(2, weight=1)

    def _select_file(self):
        path = filedialog.askopenfilename(
            title="Seleccionar archivo de datos",
            filetypes=[
                ("Todos los soportados", "*.csv *.tsv *.txt *.xlsx *.xls *.json *.parquet"),
                ("CSV / TSV / TXT", "*.csv *.tsv *.txt"),
                ("Excel", "*.xlsx *.xls"),
                ("JSON", "*.json"),
                ("Parquet", "*.parquet"),
            ]
        )
        if not path:
            return
        self.upload_filepath = path
        self.file_label.configure(text=Path(path).name)
        self.table_entry.delete(0, "end")
        self.table_entry.insert(0, Path(path).stem.lower().replace(" ", "_"))

        try:
            ext = Path(path).suffix.lower()
            if ext == ".csv":
                self.upload_df = pd.read_csv(path, nrows=100, on_bad_lines="skip")
            elif ext in (".tsv", ".txt"):
                self.upload_df = pd.read_csv(path, sep="\t", nrows=100, on_bad_lines="skip")
            elif ext in (".xlsx", ".xls"):
                self.upload_df = pd.read_excel(path, nrows=100)
            elif ext == ".json":
                self.upload_df = pd.read_json(path)
            elif ext == ".parquet":
                self.upload_df = pd.read_parquet(path)
                self.upload_df = self.upload_df.head(100)
            self._populate_preview(self.upload_df)
            self.preview_info.configure(text=f"{len(self.upload_df)} filas × {len(self.upload_df.columns)} columnas (vista previa)")
            self.load_btn.configure(state="normal")
        except Exception as e:
            self.preview_info.configure(text=f"Error: {e}", text_color="red")
            self.load_btn.configure(state="disabled")

    def _populate_preview(self, df):
        tree = self.preview_tree
        tree.delete(*tree.get_children())
        tree["columns"] = list(df.columns)
        for c in df.columns:
            tree.heading(c, text=str(c))
            tree.column(c, width=100, minwidth=60)
        for _, row in df.head(20).iterrows():
            tree.insert("", "end", values=[str(v) if v is not None else "" for v in row])

    def _load_to_db(self):
        if self.upload_df is None or not self.upload_filepath:
            return
        table = self.table_entry.get().strip()
        if not table:
            self.load_status.configure(text="⚠️  Especifica el nombre de la tabla destino", text_color="orange")
            return

        self.load_btn.configure(state="disabled", text="⏳  Cargando...")
        self.load_status.configure(text="", text_color="gray")
        self.update()

        def task():
            try:
                input_dir = Path(self.config_data["paths"]["input_dir"])
                input_dir.mkdir(parents=True, exist_ok=True)
                dest = input_dir / Path(self.upload_filepath).name
                if not dest.exists() or not Path(self.upload_filepath).samefile(dest):
                    shutil.copy2(self.upload_filepath, dest)

                result = run_pipeline(
                    dest,
                    engine=self.engine,
                    config=self.config_data,
                    target_table=table,
                    dataset_name=Path(self.upload_filepath).stem,
                    force=True,
                )
                self.after(0, lambda: self._load_done(result))
            except Exception as e:
                self.after(0, lambda: self._load_done({"status": "failed", "error": str(e)}))

        threading.Thread(target=task, daemon=True).start()

    def _load_done(self, result):
        self.load_btn.configure(state="normal", text="🚀  Cargar a DB")
        if result["status"] == "success":
            self.load_status.configure(text=f"✅  {result['rows']} filas cargadas exitosamente", text_color="green")
        elif result["status"] == "skipped":
            self.load_status.configure(text=f"⏭️  Archivo ya procesado: {result.get('reason', '')}", text_color="orange")
        else:
            self.load_status.configure(text=f"❌  Error: {result.get('error', 'desconocido')}", text_color="red")

    # ── LOGS ───────────────────────────────────────

    def _render_logs(self):
        self._clear_frame(self.frames["logs"])
        f = self.frames["logs"]
        f.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(f, text="📋 ETL Logs", font=ctk.CTkFont(size=20, weight="bold"), anchor="w")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        # Filters
        filter_frame = ctk.CTkFrame(f, fg_color="transparent")
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        filter_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(filter_frame, text="Estado:").grid(row=0, column=0, padx=(0, 5))
        self.log_status_var = ctk.StringVar(value="todos")
        status_menu = ctk.CTkOptionMenu(filter_frame, values=["todos", "success", "failed", "running"], variable=self.log_status_var, command=lambda _: self._refresh_logs())
        status_menu.grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(filter_frame, text="Límite:").grid(row=0, column=2, padx=(20, 5))
        self.log_limit_var = ctk.StringVar(value="50")
        limit_menu = ctk.CTkOptionMenu(filter_frame, values=["10", "25", "50", "100", "500"], variable=self.log_limit_var, command=lambda _: self._refresh_logs())
        limit_menu.grid(row=0, column=3, sticky="w")

        refresh_btn = ctk.CTkButton(filter_frame, text="🔄  Refrescar", width=100, command=self._refresh_logs)
        refresh_btn.grid(row=0, column=4, padx=(20, 0))

        # Table
        table_frame = ctk.CTkFrame(f)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        self.log_tree = ttk.Treeview(
            table_frame,
            columns=("ID", "Archivo", "Dataset", "Estado", "Filas", "Error", "Inicio"),
            show="headings",
        )
        cols = self.log_tree["columns"]
        headers = ("ID", "Archivo", "Dataset", "Estado", "Filas", "Error", "Inicio")
        widths = (50, 200, 120, 80, 60, 250, 150)
        for h, c, w in zip(headers, cols, widths):
            self.log_tree.heading(c, text=h)
            self.log_tree.column(c, width=w, minwidth=40)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=vsb.set)
        self.log_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        f.grid_rowconfigure(2, weight=1)
        self._refresh_logs()

    def _refresh_logs(self):
        self.log_tree.delete(*self.log_tree.get_children())
        try:
            session = get_session(self.engine)
            q = session.query(ETLJob).order_by(ETLJob.started_at.desc())
            status = self.log_status_var.get()
            if status != "todos":
                q = q.filter(ETLJob.status == status)
            limit = int(self.log_limit_var.get())
            jobs = q.limit(limit).all()
            for j in jobs:
                err = (j.error or "")[:80]
                inicio = j.started_at.strftime("%Y-%m-%d %H:%M") if j.started_at else ""
                self.log_tree.insert("", "end", values=(j.id, j.filename, j.dataset, j.status, j.rows_loaded, err, inicio))
            session.close()
        except Exception as e:
            self.log_tree.insert("", "end", values=("", "Error", str(e), "", "", "", ""))

    # ── SETTINGS ───────────────────────────────────

    def _render_settings(self):
        self._clear_frame(self.frames["settings"])
        f = self.frames["settings"]
        f.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(f, text="⚙️ Configuración", font=ctk.CTkFont(size=20, weight="bold"), anchor="w")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))

        notebook = ctk.CTkTabview(f)
        notebook.grid(row=1, column=0, sticky="nsew")
        f.grid_rowconfigure(1, weight=1)

        # General
        tab_general = notebook.add("General")
        general_text = ctk.CTkTextbox(tab_general, wrap="word")
        general_text.pack(fill="both", expand=True, padx=10, pady=10)
        general_text.insert("1.0", f"Backend: {self.config_data['database']['backend']}\n")
        general_text.insert("end", f"Ruta DB: {self.config_data['database'].get('sqlite_path', 'N/A')}\n")
        general_text.insert("end", f"Input dir: {self.config_data['paths']['input_dir']}\n")
        general_text.insert("end", f"Processed dir: {self.config_data['paths']['processed_dir']}\n")
        general_text.insert("end", f"ETL batch size: {self.config_data['etl']['batch_size']}\n")
        general_text.insert("end", f"Idempotent: {self.config_data['etl']['idempotent']}\n")
        general_text.insert("end", f"Scheduler: {'ON' if self.config_data['scheduler']['enabled'] else 'OFF'} ({self.config_data['scheduler']['interval_minutes']}min)\n")
        general_text.insert("end", f"Watcher: {'ON' if self.config_data['watcher']['enabled'] else 'OFF'}\n")
        general_text.configure(state="disabled")

        # Datasets
        tab_datasets = notebook.add("Datasets")
        datasets_text = ctk.CTkTextbox(tab_datasets, wrap="word")
        datasets_text.pack(fill="both", expand=True, padx=10, pady=10)
        datasets = self.config_data.get("datasets", {})
        if datasets:
            for name, ds in datasets.items():
                datasets_text.insert("end", f"[{name}]\n")
                for k, v in ds.items():
                    datasets_text.insert("end", f"  {k}: {v}\n")
                datasets_text.insert("end", "\n")
        else:
            datasets_text.insert("1.0", "No hay datasets configurados.")
        datasets_text.configure(state="disabled")

        # Database tables
        tab_tables = notebook.add("Tablas")
        tables_text = ctk.CTkTextbox(tab_tables, wrap="word")
        tables_text.pack(fill="both", expand=True, padx=10, pady=10)
        try:
            from sqlalchemy import inspect
            inspector = inspect(self.engine)
            for tname in inspector.get_table_names():
                tables_text.insert("end", f"📋 {tname}\n")
                for col in inspector.get_columns(tname):
                    tables_text.insert("end", f"  ├ {col['name']} ({col['type']})\n")
                tables_text.insert("end", "\n")
        except Exception as e:
            tables_text.insert("1.0", f"Error: {e}")
        tables_text.configure(state="disabled")

        # Actions
        actions_frame = ctk.CTkFrame(f, fg_color="transparent")
        actions_frame.grid(row=2, column=0, sticky="ew", pady=(15, 0))
        actions_frame.grid_columnconfigure((0, 1), weight=1)

        migrate_btn = ctk.CTkButton(actions_frame, text="🔄  Correr migraciones", command=self._run_migrations_click)
        migrate_btn.grid(row=0, column=0, padx=5)

        refresh_btn = ctk.CTkButton(actions_frame, text="🔁  Recargar config", command=self._reload_config)
        refresh_btn.grid(row=0, column=1, padx=5)

    def _run_migrations_click(self):
        try:
            run_migrations(self.engine, self.config_data)
            self._show_toast("✅ Migraciones completadas")
        except Exception as e:
            self._show_toast(f"❌ Error: {e}")

    def _reload_config(self):
        self.config_data = load_config()
        self.show_frame("settings")
        self._show_toast("✅ Configuración recargada")

    def _show_toast(self, message):
        toast = ctk.CTkToplevel(self)
        toast.title("")
        toast.geometry("400x60+400+400")
        toast.attributes("-topmost", True)
        toast.resizable(False, False)
        toast.after(2500, toast.destroy)
        label = ctk.CTkLabel(toast, text=message, font=ctk.CTkFont(size=14))
        label.pack(expand=True, fill="both", padx=20, pady=15)

    def on_close(self):
        if self._watcher_observer:
            self._watcher_observer.stop()
            self._watcher_observer.join()
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        if self._embedded_pg:
            self._embedded_pg.stop()
        self.destroy()


def run_desktop():
    app = RealViewApp()
    app.mainloop()


if __name__ == "__main__":
    run_desktop()
