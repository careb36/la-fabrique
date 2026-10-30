<#
.SYNOPSIS
    Arranca La Fabrique y el asistente de voz MARK LVI como un solo producto.

.DESCRIPTION
    Deja el producto entero funcionando con un comando:

      1. crea los entornos de Python si faltan (.venv-backend y profesor3\.venv);
      2. instala las dependencias la primera vez (Poetry para el backend, pip
         para el asistente);
      3. arranca el backend de la fábrica y el asistente, y los para juntos con
         Ctrl+C.

    Sin Postgres ni NATS: la base de datos es SQLite y los servicios opcionales
    se desactivan solos.

    Si Windows bloquea el script ("la ejecución de scripts está deshabilitada"),
    lánzalo así:

      powershell -ExecutionPolicy Bypass -File .\arrancar.ps1

    O haz doble clic en arrancar.cmd.

.EXAMPLE
    .\arrancar.ps1
    Arranca todo y abre el asistente.

.EXAMPLE
    .\arrancar.ps1 -Instalar
    Fuerza la creación de entornos e instalación de dependencias.

.EXAMPLE
    .\arrancar.ps1 -SoloBackend -Puerto 8123
    Solo la API de la fábrica, en otro puerto (útil para probar la voz a mano).
#>
[CmdletBinding()]
param(
    [switch]$SoloBackend,
    [switch]$SoloAsistente,
    [string]$Url,
    [int]$Puerto,
    [string]$Clave,
    [string]$Empresa,
    [switch]$Instalar,
    [switch]$Reinstalar,
    [switch]$Preparar
)

$ErrorActionPreference = 'Stop'
# Un comando nativo que devuelve != 0 no debe abortar el script: lo comprobamos.
$PSNativeCommandUseErrorActionPreference = $false

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $OutputEncoding = [Console]::OutputEncoding
} catch {
    # Consolas antiguas: seguimos sin UTF-8.
}

function Write-Paso([string]$Texto) {
    Write-Host ""
    Write-Host "== $Texto" -ForegroundColor Cyan
}

function Write-Ok([string]$Texto) {
    Write-Host "   OK  $Texto" -ForegroundColor Green
}

function Write-Aviso([string]$Texto) {
    Write-Host "   !!  $Texto" -ForegroundColor Yellow
}

# --- Dónde estamos -----------------------------------------------------------

$Root = if ($PSScriptRoot) {
    $PSScriptRoot
} else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location -LiteralPath $Root

$Launcher = Join-Path $Root 'run_fusion.py'
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "No encuentro run_fusion.py en '$Root'. Ejecuta este script desde la carpeta del proyecto fusionado."
}

$BackendDir = Join-Path (Join-Path $Root 'la-fabrique') 'backend'
$AssistantDir = Join-Path $Root 'profesor3'
$BackendVenv = Join-Path $Root '.venv-backend'
$AssistantVenv = Join-Path $AssistantDir '.venv'

# --- Utilidades --------------------------------------------------------------

function Get-VenvPython([string]$Dir) {
    $candidates = @(
        @('Scripts', 'python.exe'),
        @('bin', 'python'),
        @('bin', 'python3')
    )
    foreach ($parts in $candidates) {
        $path = $Dir
        foreach ($part in $parts) { $path = Join-Path $path $part }
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}

function Find-SystemPython {
    # Preferimos el lanzador 'py' de Windows, que elige la versión instalada.
    $probes = @(
        @{ Exe = 'py'; Prefix = @('-3.13') },
        @{ Exe = 'py'; Prefix = @('-3.12') },
        @{ Exe = 'py'; Prefix = @('-3.11') },
        @{ Exe = 'py'; Prefix = @('-3') },
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'python3'; Prefix = @() }
    )
    foreach ($probe in $probes) {
        if (-not (Get-Command $probe.Exe -ErrorAction SilentlyContinue)) { continue }
        $check = @($probe.Prefix) + @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)')
        & $probe.Exe @check 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $probe }
    }
    return $null
}

function New-BackendVenv($SystemPython) {
    Write-Paso "Creando entorno del backend en $BackendVenv"
    $arguments = @($SystemPython.Prefix) + @('-m', 'venv', $BackendVenv)
    & $SystemPython.Exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "No pude crear el entorno del backend. Instala Python 3.11+ desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH')."
    }
    Write-Ok "Entorno creado"
}

function Install-BackendDependencies([string]$Python) {
    Write-Paso "Instalando dependencias del backend (Poetry + proyecto)"
    & $Python -m pip install --quiet --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip no pudo actualizarse en $Python" }
    & $Python -m pip install --quiet --disable-pip-version-check poetry
    if ($LASTEXITCODE -ne 0) { throw "No pude instalar Poetry en $Python" }

    # Poetry ignora el venv desde el que lo lanzas: sin VIRTUAL_ENV instala en
    # el Python del sistema. Se lo decimos y le ponemos su Scripts/bin delante.
    $previousVenv = $env:VIRTUAL_ENV
    $previousCreate = $env:POETRY_VIRTUALENVS_CREATE
    $previousPath = $env:PATH
    $env:VIRTUAL_ENV = $script:BackendVenv
    $env:POETRY_VIRTUALENVS_CREATE = 'false'
    $env:PATH = (Split-Path -Parent $Python) + [IO.Path]::PathSeparator + $env:PATH
    Push-Location -LiteralPath $BackendDir
    try {
        & $Python -m poetry install --no-interaction
        if ($LASTEXITCODE -ne 0) { throw "Poetry no pudo instalar el backend (revisa la salida de arriba)." }
    } finally {
        Pop-Location
        $env:PATH = $previousPath
        $env:POETRY_VIRTUALENVS_CREATE = $previousCreate
        $env:VIRTUAL_ENV = $previousVenv
    }
    Write-Ok "Backend listo"
}

function Install-AssistantDependencies([string]$Python) {
    $requirements = Join-Path $AssistantDir 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirements)) {
        throw "No encuentro ${requirements}: revisa que la carpeta profesor3 esté completa."
    }
    Write-Paso "Instalando dependencias del asistente (PyQt6, Gemini...); la primera vez tarda"
    & $Python -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "No pude instalar las dependencias del asistente." }
    Write-Ok "Asistente listo"
}

function Reset-Venv([string]$Dir) {
    if (Test-Path -LiteralPath $Dir) {
        Write-Aviso "Borrando $Dir para reinstalar"
        Remove-Item -LiteralPath $Dir -Recurse -Force
    }
}

function Test-Imports([string]$Python, [string]$Module) {
    if ([string]::IsNullOrEmpty($Python)) { return $false }
    & $Python -c "import $Module" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# --- Entornos ----------------------------------------------------------------

$backendPython = Get-VenvPython $BackendVenv
$assistantPython = Get-VenvPython $AssistantVenv

if ($Reinstalar) {
    if (-not $SoloAsistente) { Reset-Venv $BackendVenv }
    if (-not $SoloBackend) { Reset-Venv $AssistantVenv }
    $backendPython = $null
    $assistantPython = $null
}

$needsBackend = (-not $SoloAsistente) -and ($Instalar -or ($null -eq $backendPython))
$needsAssistant = (-not $SoloBackend) -and ($Instalar -or ($null -eq $assistantPython))

if ($needsBackend -or $needsAssistant) {
    $systemPython = Find-SystemPython
    if ($null -eq $systemPython) {
        throw "Necesito Python 3.11 o superior. Instálalo desde https://www.python.org/downloads/ y marca 'Add python.exe to PATH'."
    }
    Write-Host "Usando $($systemPython.Exe) $($systemPython.Prefix -join ' ')" -ForegroundColor DarkGray

    if ($needsBackend) {
        if ($null -eq (Get-VenvPython $BackendVenv)) { New-BackendVenv $systemPython }
        $backendPython = Get-VenvPython $BackendVenv
        Install-BackendDependencies $backendPython
    }
    if ($needsAssistant) {
        if ($null -eq (Get-VenvPython $AssistantVenv)) {
            Write-Paso "Creando entorno del asistente en $AssistantVenv"
            $arguments = @($systemPython.Prefix) + @('-m', 'venv', $AssistantVenv)
            & $systemPython.Exe @arguments
            if ($LASTEXITCODE -ne 0) { throw "No pude crear el entorno del asistente." }
        }
        $assistantPython = Get-VenvPython $AssistantVenv
        Install-AssistantDependencies $assistantPython
    }
}

$backendPython = Get-VenvPython $BackendVenv
$assistantPython = Get-VenvPython $AssistantVenv
if ((-not $SoloAsistente) -and ($null -eq $backendPython)) { throw "Falta el entorno del backend en $BackendVenv" }
if ((-not $SoloBackend) -and ($null -eq $assistantPython)) { throw "Falta el entorno del asistente en $AssistantVenv" }

# Un venv puede existir y estar a medias (una instalación cortada por la red
# deja el intérprete creado pero sin paquetes). En ese caso se repara solo en
# vez de mandar al usuario a ejecutar pip a mano.
if ((-not $SoloAsistente) -and (-not (Test-Imports $backendPython 'fastapi'))) {
    Write-Aviso "Al entorno del backend le faltan dependencias; las instalo"
    Install-BackendDependencies $backendPython
}
if ((-not $SoloBackend) -and (-not (Test-Imports $assistantPython 'PyQt6'))) {
    Write-Aviso "Al entorno del asistente le faltan dependencias; las instalo"
    Install-AssistantDependencies $assistantPython
}

if ($Preparar) {
    Write-Host ""
    Write-Ok "Entornos listos. Arranca con: .\arrancar.ps1"
    exit 0
}

# --- Arranque ----------------------------------------------------------------

$launcherArgs = @()
if ($SoloBackend) { $launcherArgs += '--backend-only' }
if ($SoloAsistente) { $launcherArgs += '--assistant-only' }
if ($Url) { $launcherArgs += @('--url', $Url) }
if ($Puerto -gt 0) { $launcherArgs += @('--port', "$Puerto") }
if ($Clave) { $launcherArgs += @('--voice-key', $Clave) }
if ($Empresa) { $launcherArgs += @('--company', $Empresa) }
if ($null -ne $backendPython) { $launcherArgs += @('--backend-python', $backendPython) }
if ($null -ne $assistantPython) { $launcherArgs += @('--assistant-python', $assistantPython) }

$runner = if ($SoloAsistente) { $assistantPython } else { $backendPython }

Write-Paso "Arrancando la fábrica y el asistente (Ctrl+C para parar los dos)"
& $runner -u $Launcher @launcherArgs
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ""
    Write-Host "El producto terminó con código $code." -ForegroundColor Red
}
exit $code
