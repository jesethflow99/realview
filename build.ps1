<# 
    RealView Build Script -- PowerShell
    Build portable Windows executable with embedded PostgreSQL
#>
param(
    [switch]$SkipPG = $false,
    [switch]$Verbose = $false
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host '=== RealView -- Build para Windows ===' -ForegroundColor Cyan

# 1. Check Python
Write-Host '[1/6] Verificando Python...' -ForegroundColor Yellow
try {
    python --version 2>&1 | Out-Null
} catch {
    Write-Host '[ERROR] Python no encontrado. Instala desde python.org' -ForegroundColor Red
    pause
    exit 1
}

# 2. Check Tkinter
Write-Host '[2/6] Verificando Tkinter...' -ForegroundColor Yellow
$tk = python -c "import tkinter; print('ok')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host '[ERROR] Tkinter no disponible. Reinstala Python con tcl/tk' -ForegroundColor Red
    pause
    exit 1
}
Write-Host '  Tkinter OK' -ForegroundColor Green

# 3. Create virtualenv if missing
Write-Host '[3/6] Preparando virtualenv...' -ForegroundColor Yellow
if (-not (Test-Path 'venv\Scripts\python.exe')) {
    Write-Host '  Creando virtualenv...'
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[ERROR] No se pudo crear virtualenv' -ForegroundColor Red
        pause
        exit 1
    }
}

# 4. Install dependencies
Write-Host '[4/6] Instalando dependencias...' -ForegroundColor Yellow
$venvPython = '.\venv\Scripts\python.exe'
& $venvPython -m pip install -q --upgrade pip
& $venvPython -m pip install -q -r requirements.txt
& $venvPython -m pip install -q pyinstaller
Write-Host '  Dependencias OK' -ForegroundColor Green

# 5. PostgreSQL portable
if (-not $SkipPG) {
    Write-Host '[5/6] Verificando PostgreSQL portatil...' -ForegroundColor Yellow
    if (-not (Test-Path 'pg\pgsql\bin\pg_ctl.exe')) {
        Write-Host '  PostgreSQL no encontrado.'
        Write-Host '  AVISO: La descarga automatica puede fallar (error 403).' -ForegroundColor Magenta
        Write-Host '  Opcion 1: Descarga manual de https://www.enterprisedb.com/download-postgresql-binaries' -ForegroundColor Magenta
        Write-Host '  Opcion 2: Usa backend = postgresql en config/settings.toml si ya tienes PG instalado' -ForegroundColor Magenta
        Write-Host '  Opcion 3: Corre: python download_pg.py --dir .' -ForegroundColor Magenta
        $choice = Read-Host '  Intentar descarga automatica? (s/N)'
        if ($choice -eq 's' -or $choice -eq 'S') {
            & $venvPython download_pg.py --dir .
            if ($LASTEXITCODE -ne 0) {
                Write-Host '  [ADVERTENCIA] Descarga fallo. El ejecutable se construira sin PostgreSQL.' -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host '  PostgreSQL portatil encontrado en pg\' -ForegroundColor Green
    }
} else {
    Write-Host '[5/6] PostgreSQL omitido (--SkipPG)' -ForegroundColor Yellow
}

# 6. Build with PyInstaller
Write-Host '[6/6] Construyendo ejecutable...' -ForegroundColor Yellow

$addData = 'config/settings.toml;config'
if (Test-Path 'pg\pgsql\bin\pg_ctl.exe') {
    $addData = 'config/settings.toml;config', 'pg;pgsql'
}

Write-Host '  PyInstaller empaquetando... (puede tomar varios minutos)' -ForegroundColor Gray

$pyiArgs = @(
    '--name', 'RealView',
    '--onefile',
    '--windowed',
    '--add-data', 'config/settings.toml;config',
    '--hidden-import', 'sqlalchemy',
    '--hidden-import', 'sqlalchemy.dialects.sqlite',
    '--hidden-import', 'sqlalchemy.dialects.postgresql',
    '--hidden-import', 'pandas',
    '--hidden-import', 'openpyxl',
    '--hidden-import', 'tomli',
    '--hidden-import', 'customtkinter',
    '--hidden-import', 'PIL',
    '--hidden-import', 'PIL._tkinter_finder',
    '--collect-all', 'customtkinter',
    'src/desktop.py'
)

if (Test-Path 'pg\pgsql\bin\pg_ctl.exe') {
    $pyiArgs += @('--add-data', 'pg;pgsql')
}

& $venvPython -m PyInstaller @pyiArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '=== Build exitoso! ===' -ForegroundColor Green
    Write-Host '  Ejecutable: dist\RealView.exe' -ForegroundColor White
    Write-Host ''
    Write-Host '  Al ejecutar por primera vez:' -ForegroundColor Gray
    Write-Host '    1. Inicializa PostgreSQL en pgdata\' -ForegroundColor Gray
    Write-Host '    2. Crea la base de datos realview' -ForegroundColor Gray
    Write-Host '    3. Abre la interfaz grafica' -ForegroundColor Gray
    Write-Host ''
    Write-Host '  Power BI -> localhost:5432 / realview (DirectQuery)' -ForegroundColor White
} else {
    Write-Host ''
    Write-Host '[ERROR] Fallo el build con PyInstaller' -ForegroundColor Red
}

pause
