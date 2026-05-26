@echo off
chcp 65001 >nul
title RealView Build

echo === RealView — Build para Windows ===
echo.

REM Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado. Instalalo desde python.org
    pause
    exit /b 1
)

REM Verificar que tiene Tkinter (viene con Python en Windows)
python -c "import tkinter; print('✅ Tkinter OK')" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Tkinter no disponible. Reinstala Python con la opcion "tcl/tk"
    pause
    exit /b 1
)

REM Crear virtualenv si no existe
if not exist venv (
    echo Creando virtualenv...
    python -m venv venv
)

REM Activar venv
call venv\Scripts\activate.bat

REM Instalar dependencias
echo Instalando dependencias...
pip install -U pip >nul
pip install -r requirements.txt
pip install pyinstaller

REM Descargar PostgreSQL portátil (si no existe)
echo.
echo === Verificando PostgreSQL portátil ===
if not exist pg\pgsql\bin\pg_ctl.exe (
    echo Descargando PostgreSQL portátil (~130MB)...
    python download_pg.py
) else (
    echo PostgreSQL portátil encontrado en pg\
)

echo.
echo === Construyendo ejecutable con PyInstaller ===
echo.

pyinstaller ^
    --name "RealView" ^
    --onefile ^
    --windowed ^
    --add-data "config/settings.toml;config" ^
    --add-data "pg;pgsql" ^
    --hidden-import sqlalchemy ^
    --hidden-import sqlalchemy.dialects.sqlite ^
    --hidden-import sqlalchemy.dialects.postgresql ^
    --hidden-import pandas ^
    --hidden-import openpyxl ^
    --hidden-import tomli ^
    --hidden-import customtkinter ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    --collect-all customtkinter ^
    src/desktop.py

if %errorlevel% equ 0 (
    echo.
    echo ✅  Build exitoso!
    echo    Ejecutable: dist\RealView.exe
    echo.
    echo    Al ejecutarlo por primera vez:
    echo      1. Inicializa PostgreSQL en pgdata\
    echo      2. Crea la base de datos 'realview'
    echo      3. Abre la interfaz gráfica
    echo.
    echo    Power BI se conecta a: localhost:5432 / realview
) else (
    echo.
    echo ❌  Error en el build. Revisa los mensajes arriba.
)

pause
