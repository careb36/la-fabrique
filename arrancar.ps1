<#
.SYNOPSIS
    Arranca La Fabrique y el asistente de voz MARK LVI como un solo producto.

.DESCRIPTION
    Deja el producto entero funcionando con un comando:

      1. busca Python 3.12 (o 3.11+ si no está) y comprueba que arranca;
      2. crea solo los entornos que faltan o están realmente dañados;
      3. instala las dependencias que falten (Poetry y, si la red falla, pip
         con las versiones exactas de poetry.lock);
      4. verifica los módulos esenciales y distingue "falta" de "está roto";
      5. arranca el backend y el asistente, y los para juntos con Ctrl+C.

    Sin Postgres ni NATS: la base de datos es SQLite y los servicios opcionales
    se desactivan solos. Todo queda registrado en logs\.

    Si Windows bloquea el script ("la ejecución de scripts está deshabilitada"),
    lánzalo así:

      powershell -ExecutionPolicy Bypass -File .\arrancar.ps1

    O haz doble clic en arrancar.cmd.

.PARAMETER Python
    Intérprete concreto para crear los entornos (por defecto: 3.12).

.PARAMETER Instalar
    Revisa y completa las dependencias aunque los entornos ya existan.

.PARAMETER Reinstalar
    Mueve los entornos actuales a .venv-backend.roto-<fecha> y los rehace.
    Nunca ocurre solo: hay que pedirlo.

.EXAMPLE
    .\arrancar.ps1
    Arranca todo y abre el asistente.

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
    [switch]$Preparar,
    [string]$Python
)

# Los comandos nativos (pip, poetry, python) escriben avisos por stderr. Con
# $ErrorActionPreference='Stop', PowerShell 5.1 convierte ese stderr en
# NativeCommandError y aborta a mitad de la instalación; comprobamos los
# códigos de salida nosotros mismos.
$ErrorActionPreference = 'Continue'
$PSNativeCommandUseErrorActionPreference = $false

# La consola de Windows arranca en cp850/cp1252 y los acentos y flechas
# saldrían como «Ã©». Se pone UTF-8 antes de imprimir nada.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # consolas sin handle real (IDE, redirección): se sigue igual
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8:replace'

$script:BackendModules = @(
    'fastapi', 'uvicorn', 'sqlmodel', 'sqlalchemy', 'pydantic',
    'httpx', 'langchain_core', 'langsmith'
)
$script:AssistantModules = @('PyQt6', 'PyQt6.QtWidgets', 'google.genai', 'sounddevice', 'numpy')
$script:PreferredMinor = 12

# --- Dónde estamos -----------------------------------------------------------

$Root = if ($PSScriptRoot) {
    $PSScriptRoot
} else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}
Set-Location -LiteralPath $Root

$Launcher = Join-Path $Root 'run_fusion.py'
if (-not (Test-Path -LiteralPath $Launcher)) {
    Write-Host "XX  No encuentro run_fusion.py en '$Root'." -ForegroundColor Red
    exit 1
}

$BackendDir = Join-Path (Join-Path $Root 'la-fabrique') 'backend'
$AssistantDir = Join-Path $Root 'profesor3'
$BackendVenv = Join-Path $Root '.venv-backend'
$AssistantVenv = Join-Path $AssistantDir '.venv'
$LockFile = Join-Path $BackendDir 'poetry.lock'
$LogDir = Join-Path $Root 'logs'

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir ("arranque-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")

# $IsWindows solo existe en PowerShell 7; en 5.1 hay que mirar el entorno.
$script:OnWindows = if ($null -eq $IsWindows) {
    ($env:OS -eq 'Windows_NT')
} else {
    [bool]$IsWindows
}

# --- Mensajes ----------------------------------------------------------------

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

function Write-Fallo([string]$Texto) {
    Write-Host "   XX  $Texto" -ForegroundColor Red
}

function Write-Detalle([string]$Texto) {
    if (-not [string]::IsNullOrWhiteSpace($Texto)) {
        foreach ($line in ($Texto -split "`r?`n")) {
            if ($line.Trim()) { Write-Host "       $line" -ForegroundColor DarkGray }
        }
    }
}

# --- Procesos de Python ------------------------------------------------------

function ConvertTo-ArgumentString([string[]]$Arguments) {
    # Start-Process une los argumentos con espacios: hay que citar los que los
    # llevan (rutas con espacios, código de una línea...).
    $quoted = foreach ($argument in $Arguments) {
        if ($null -eq $argument) { continue }
        if ($argument -match '\s') { '"' + ($argument -replace '"', '\"') + '"' } else { $argument }
    }
    return ($quoted -join ' ')
}

# Ejecuta Python sin que PowerShell interprete su stderr. Devuelve código de
# salida y ambos flujos: así un import roto nunca se confunde con una
# dependencia ausente ni aborta el script con NativeCommandError.
function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int]$TimeoutSeconds = 120
    )
    $outFile = [IO.Path]::GetTempFileName()
    $errFile = [IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath $Exe -ArgumentList (ConvertTo-ArgumentString $Arguments) `
            -NoNewWindow -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            return [pscustomobject]@{ ExitCode = -2; StdOut = ''; StdErr = "no terminó en $TimeoutSeconds s" }
        }
        $stdout = if (Test-Path -LiteralPath $outFile) { Get-Content -LiteralPath $outFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $stderr = if (Test-Path -LiteralPath $errFile) { Get-Content -LiteralPath $errFile -Raw -ErrorAction SilentlyContinue } else { '' }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; StdOut = $stdout; StdErr = $stderr }
    } catch {
        return [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = $_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# Sondas en archivo: nada de código con comillas dentro de -c.
$script:InfoProbe = Join-Path $LogDir 'probe_python_info.py'
$script:ModuleProbe = Join-Path $LogDir 'probe_modules.py'

@'
import json, platform, struct, sys
print(json.dumps({
    "version": "%d.%d.%d" % sys.version_info[:3],
    "major": sys.version_info[0],
    "minor": sys.version_info[1],
    "bits": struct.calcsize("P") * 8,
    "machine": platform.machine(),
    "prefix": sys.prefix,
    "base_prefix": getattr(sys, "base_prefix", sys.prefix),
}))
'@ | Set-Content -LiteralPath $script:InfoProbe -Encoding UTF8

@'
import importlib, json, sys, traceback
missing, broken = [], []
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        missing.append("%s (%s)" % (name, exc))
    except Exception:
        broken.append("%s\n%s" % (name, traceback.format_exc()))
print(json.dumps({"missing": missing, "broken": broken}))
raise SystemExit(1 if (missing or broken) else 0)
'@ | Set-Content -LiteralPath $script:ModuleProbe -Encoding UTF8

function Get-PythonInfo([string]$Exe, [string[]]$Prefix = @()) {
    if ([string]::IsNullOrWhiteSpace($Exe)) { return $null }
    # El prefijo importa: 'py' sin -3.12 resuelve la versión por defecto del
    # sistema, así que hay que preguntar por la versión concreta.
    $probe = Invoke-Python -Exe $Exe -Arguments (@($Prefix) + @($script:InfoProbe)) -TimeoutSeconds 90
    if ($probe.ExitCode -ne 0 -or -not $probe.StdOut) { return $null }
    $line = ($probe.StdOut -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
    if (-not $line) { return $null }
    try {
        $info = $line | ConvertFrom-Json
    } catch {
        return $null
    }
    $info | Add-Member -NotePropertyName Exe -NotePropertyValue $Exe -Force
    $info | Add-Member -NotePropertyName Prefix -NotePropertyValue @($Prefix) -Force
    return $info
}

# Comprueba módulos en un solo proceso e informa de qué falta y qué está roto.
function Test-PythonModules {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Modules = @()
    )
    $result = Invoke-Python -Exe $Exe -Arguments (@($script:ModuleProbe) + @($Modules)) -TimeoutSeconds 300
    $payload = $null
    if ($result.StdOut) {
        $line = ($result.StdOut -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
        if ($line) { try { $payload = $line | ConvertFrom-Json } catch { $payload = $null } }
    }
    $missing = @()
    $broken = @()
    if ($payload) {
        $missing = @($payload.missing | Where-Object { $_ })
        $broken = @($payload.broken | Where-Object { $_ })
    }
    return [pscustomobject]@{
        ExitCode = $result.ExitCode
        Missing  = $missing
        Broken   = $broken
        Output   = (($result.StdErr + $result.StdOut) -as [string]).Trim()
        Parsed   = ($null -ne $payload)
    }
}

function Write-ModuleReport($Report, [string]$Etiqueta) {
    if ($Report.Missing.Count -gt 0) {
        Write-Fallo "A $Etiqueta le faltan módulos:"
        foreach ($item in $Report.Missing) { Write-Detalle $item }
    }
    if ($Report.Broken.Count -gt 0) {
        Write-Fallo "En $Etiqueta hay módulos instalados que no importan:"
        foreach ($item in $Report.Broken) { Write-Detalle $item }
    }
    if (-not $Report.Parsed) {
        Write-Fallo "No pude comprobar $Etiqueta (código $($Report.ExitCode)):"
        Write-Detalle $Report.Output
    }
}

# --- Entornos ----------------------------------------------------------------

function Get-VenvPython([string]$Dir) {
    if (-not (Test-Path -LiteralPath $Dir)) { return $null }
    # Un venv de Windows tiene Scripts\python.exe y uno de Linux bin/python.
    # Mezclarlos producía "no se puede ejecutar un documento en medio de una
    # canalización" al usar .venv-backend\bin\python en Windows.
    $candidates = if ($script:OnWindows) {
        @(, @('Scripts', 'python.exe'))
    } else {
        @(@('bin', 'python'), @('bin', 'python3'))
    }
    foreach ($parts in $candidates) {
        $path = $Dir
        foreach ($part in $parts) { $path = Join-Path $path $part }
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        # Que exista no basta: comprobamos que el intérprete responde.
        $info = Get-PythonInfo $path
        if ($info) { return $path }
        Write-Aviso "El intérprete $path existe pero no responde; lo ignoro."
    }
    return $null
}

function Find-SystemPython {
    $candidates = New-Object System.Collections.ArrayList

    if ($Python) {
        [void]$candidates.Add(@{ Exe = $Python; Prefix = @(); Label = 'parámetro -Python' })
    }
    if ($env:FUSION_PYTHON) {
        [void]$candidates.Add(@{ Exe = $env:FUSION_PYTHON; Prefix = @(); Label = 'variable FUSION_PYTHON' })
    }
    if ($script:OnWindows) {
        # El lanzador 'py' elige la versión instalada aunque no esté en PATH.
        [void]$candidates.Add(@{ Exe = 'py'; Prefix = @('-3.12'); Label = 'py -3.12' })
        [void]$candidates.Add(@{ Exe = (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'); Prefix = @(); Label = 'Python312 del usuario' })
        [void]$candidates.Add(@{ Exe = (Join-Path $env:ProgramFiles 'Python312\python.exe'); Prefix = @(); Label = 'Python312 de Program Files' })
        [void]$candidates.Add(@{ Exe = 'python3.12'; Prefix = @(); Label = 'python3.12' })
        [void]$candidates.Add(@{ Exe = 'py'; Prefix = @('-3.11'); Label = 'py -3.11' })
        [void]$candidates.Add(@{ Exe = 'py'; Prefix = @('-3'); Label = 'py -3' })
        [void]$candidates.Add(@{ Exe = 'python'; Prefix = @(); Label = 'python' })
    } else {
        [void]$candidates.Add(@{ Exe = 'python3.12'; Prefix = @(); Label = 'python3.12' })
        [void]$candidates.Add(@{ Exe = 'python3.11'; Prefix = @(); Label = 'python3.11' })
        [void]$candidates.Add(@{ Exe = 'python3'; Prefix = @(); Label = 'python3' })
        [void]$candidates.Add(@{ Exe = 'python'; Prefix = @(); Label = 'python' })
    }

    $usable = New-Object System.Collections.ArrayList
    foreach ($candidate in $candidates) {
        $exe = Resolve-CommandPath $candidate.Exe
        if (-not $exe) { continue }
        $info = Get-PythonInfo $exe $candidate.Prefix
        if ($null -eq $info) { continue }
        if ($info.major -lt 3 -or ($info.major -eq 3 -and $info.minor -lt 11)) {
            Write-Detalle "$($candidate.Label) ($($info.version)) es demasiado antiguo; lo salto."
            continue
        }
        $info | Add-Member -NotePropertyName Label -NotePropertyValue $candidate.Label -Force
        [void]$usable.Add($info)
    }
    foreach ($info in $usable) {
        if ($info.minor -eq $script:PreferredMinor) { return $info }
    }
    if ($usable.Count -gt 0) { return $usable[0] }
    return $null
}

function Resolve-CommandPath([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) { return $null }
    if (Test-Path -LiteralPath $Name -PathType Leaf) { return $Name }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    if ($command.Path) { return $command.Path }
    return $command.Name
}

function New-Venv([string]$Dir, $PythonInfo, [string]$Etiqueta) {
    Write-Paso "Creando entorno de $Etiqueta en $Dir"
    $venvArgs = @($PythonInfo.Prefix) + @('-m', 'venv', $Dir)
    $result = Invoke-Python -Exe $PythonInfo.Exe -Arguments $venvArgs -TimeoutSeconds 600
    if ($result.ExitCode -ne 0) {
        Write-Detalle $result.StdErr
        throw "No pude crear el entorno de $Etiqueta con $($PythonInfo.Exe) ($($PythonInfo.version))."
    }
    $venvPython = Get-VenvPython $Dir
    if (-not $venvPython) { throw "El entorno de $Etiqueta se creó pero su python no responde." }

    # ensurepip puede quedar a medias si el antivirus bloquea archivos temporales.
    $pip = Invoke-Python -Exe $venvPython -Arguments @('-m', 'pip', '--version') -TimeoutSeconds 120
    if ($pip.ExitCode -ne 0) {
        Write-Aviso "pip no funciona en $Dir; lo reparo con ensurepip"
        $repair = Invoke-Python -Exe $venvPython -Arguments @('-m', 'ensurepip', '--upgrade') -TimeoutSeconds 300
        if ($repair.ExitCode -ne 0) {
            Write-Detalle $repair.StdErr
            throw "No pude reparar pip en $Dir."
        }
    }
    Write-Ok "Entorno creado con Python $($PythonInfo.version)"
    return $venvPython
}

function Backup-Venv([string]$Dir, [string]$Motivo) {
    if (-not (Test-Path -LiteralPath $Dir)) { return }
    $backup = "$Dir.roto-" + (Get-Date -Format 'yyyyMMdd-HHmmss')
    Write-Aviso "Muevo $Dir a $backup ($Motivo)"
    Move-Item -LiteralPath $Dir -Destination $backup -Force
    Write-Ok "Copia guardada: $backup (puedes borrarla cuando todo funcione)"
}

# --- Red y certificados ------------------------------------------------------

# pip y PowerShell usan el almacén de certificados de Windows; Poetry solo trae
# certifi. Con un antivirus o proxy que inspecciona TLS, Poetry falla con
# "All attempts to connect to pypi.org failed" mientras pip funciona. Exportar
# las raíces del sistema a un PEM mantiene la verificación TLS y arregla esa
# diferencia sin desactivar nada.
function Enable-SystemCertificateBundle {
    if (-not $script:OnWindows) { return $null }
    $bundle = Join-Path $LogDir 'windows-ca-bundle.pem'
    try {
        $builder = New-Object System.Text.StringBuilder
        $count = 0
        foreach ($storeName in @('Root', 'CA')) {
            foreach ($location in @('LocalMachine', 'CurrentUser')) {
                $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($storeName, $location)
                $store.Open('ReadOnly')
                foreach ($cert in $store.Certificates) {
                    [void]$builder.AppendLine('-----BEGIN CERTIFICATE-----')
                    [void]$builder.AppendLine([Convert]::ToBase64String($cert.RawData, [System.Base64FormattingOptions]::InsertLineBreaks))
                    [void]$builder.AppendLine('-----END CERTIFICATE-----')
                    $count++
                }
                $store.Close()
            }
        }
        if ($count -eq 0) { return $null }
        Set-Content -LiteralPath $bundle -Value $builder.ToString() -Encoding ascii
        Write-Ok "Certificados del sistema exportados ($count) para Poetry y pip"
        return $bundle
    } catch {
        Write-Aviso "No pude exportar los certificados del sistema: $($_.Exception.Message)"
        return $null
    }
}

function Initialize-NetworkEnvironment {
    $bundle = Enable-SystemCertificateBundle
    if ($bundle) {
        # Respetamos lo que el usuario ya tenga (proxy corporativo, bundle
        # propio): solo rellenamos lo que falte.
        if (-not $env:REQUESTS_CA_BUNDLE) { $env:REQUESTS_CA_BUNDLE = $bundle }
        if (-not $env:SSL_CERT_FILE) { $env:SSL_CERT_FILE = $bundle }
        if (-not $env:PIP_CERT) { $env:PIP_CERT = $bundle }
    }
    if ($env:HTTPS_PROXY -or $env:HTTP_PROXY) {
        Write-Ok "Uso el proxy configurado ($($env:HTTPS_PROXY)$($env:HTTP_PROXY))"
    }
}

function Show-InstallFailure([string]$Salida) {
    Write-Detalle $Salida
    if ($Salida -match 'All attempts to connect|ConnectionError|Max retries|SSLError|CERTIFICATE') {
        Write-Aviso "Parece un problema de red/TLS, no de dependencias. Comprueba en una consola:"
        Write-Host "         python -m pip download --no-deps --dest $env:TEMP\probe httpx" -ForegroundColor DarkGray
    }
}

# --- Instalación de dependencias --------------------------------------------

function Update-Pip([string]$PythonExe) {
    Write-Detalle "Actualizando pip…"
    & $PythonExe -m pip install --quiet --disable-pip-version-check --retries 5 --timeout 60 --upgrade pip
    if ($LASTEXITCODE -ne 0) { Write-Aviso "No pude actualizar pip; sigo con el que hay." }
}

function Install-BackendDependencies([string]$PythonExe) {
    Write-Paso "Instalando dependencias del backend"
    Update-Pip $PythonExe

    $poetryOk = $false
    & $PythonExe -m pip install --quiet --disable-pip-version-check --retries 5 --timeout 60 poetry
    if ($LASTEXITCODE -eq 0) {
        # Poetry ignora el venv desde el que lo lanzas: sin VIRTUAL_ENV instala
        # en el Python del sistema. Se lo decimos y ponemos su Scripts/bin
        # delante en el PATH.
        $previousVenv = $env:VIRTUAL_ENV
        $previousCreate = $env:POETRY_VIRTUALENVS_CREATE
        $previousPath = $env:PATH
        $env:VIRTUAL_ENV = $BackendVenv
        $env:POETRY_VIRTUALENVS_CREATE = 'false'
        $env:PATH = (Split-Path -Parent $PythonExe) + [IO.Path]::PathSeparator + $env:PATH
        Push-Location -LiteralPath $BackendDir
        try {
            for ($intento = 1; $intento -le 2; $intento++) {
                Write-Detalle "poetry install (intento $intento de 2)"
                & $PythonExe -m poetry install --no-interaction
                if ($LASTEXITCODE -eq 0) { $poetryOk = $true; break }
                Start-Sleep -Seconds (2 * $intento)
            }
        } finally {
            Pop-Location
            $env:PATH = $previousPath
            $env:POETRY_VIRTUALENVS_CREATE = $previousCreate
            $env:VIRTUAL_ENV = $previousVenv
        }
        if (-not $poetryOk) {
            Write-Aviso "Poetry no pudo instalar (red/TLS). Paso a pip con las versiones exactas del lock."
        }
    } else {
        Write-Aviso "No pude instalar Poetry; instalo el backend con pip y el lock."
    }

    if (-not $poetryOk) {
        if (-not (Test-Path -LiteralPath $LockFile)) {
            throw "No encuentro poetry.lock en ${BackendDir}: no puedo instalar sin él."
        }
        $requirements = Join-Path $LogDir 'backend-requirements-lock.txt'
        $export = Join-Path (Join-Path $Root 'tools') 'lock_requirements.py'
        if (-not (Test-Path -LiteralPath $export)) {
            throw "No encuentro tools\lock_requirements.py: el proyecto está incompleto."
        }
        $exportResult = Invoke-Python -Exe $PythonExe -Arguments @($export, $LockFile, '--groups', 'main,dev', '--output', $requirements) -TimeoutSeconds 120
        if ($exportResult.ExitCode -ne 0) {
            Write-Detalle $exportResult.StdErr
            throw "No pude leer poetry.lock para generar el requirements."
        }
        Write-Detalle $exportResult.StdOut
        & $PythonExe -m pip install --disable-pip-version-check --retries 5 --timeout 60 -r $requirements
        if ($LASTEXITCODE -ne 0) {
            Show-InstallFailure "pip falló instalando las dependencias del backend."
            throw "pip no pudo instalar las dependencias del backend (código $LASTEXITCODE)."
        }
    }
    Write-Ok "Backend instalado"
}

function Install-AssistantDependencies([string]$PythonExe) {
    $requirements = Join-Path $AssistantDir 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirements)) {
        throw "No encuentro ${requirements}: revisa que la carpeta profesor3 esté completa."
    }
    Write-Paso "Instalando dependencias del asistente (PyQt6, Gemini...); la primera vez tarda"
    Update-Pip $PythonExe
    & $PythonExe -m pip install --disable-pip-version-check --retries 5 --timeout 60 -r $requirements
    if ($LASTEXITCODE -ne 0) {
        Show-InstallFailure "pip falló instalando las dependencias del asistente."
        throw "No pude instalar las dependencias del asistente (código $LASTEXITCODE)."
    }
    Write-Ok "Asistente instalado"
}

function Test-BackendReady([string]$PythonExe) {
    $report = Test-PythonModules -Exe $PythonExe -Modules $script:BackendModules
    if ($report.ExitCode -eq 0) { Write-Ok "Módulos del backend presentes"; return $true }
    Write-ModuleReport $report "el backend"
    return $false
}

function Test-AssistantReady([string]$PythonExe) {
    $report = Test-PythonModules -Exe $PythonExe -Modules $script:AssistantModules
    if ($report.ExitCode -eq 0) { Write-Ok "Módulos del asistente presentes"; return $true }
    Write-ModuleReport $report "el asistente"
    return $false
}

# --- Cuerpo ------------------------------------------------------------------

$script:ExitCode = 0
$transcript = $false
try {
    try {
        # -Path y no -LiteralPath: PowerShell 5.1 no tiene -LiteralPath aquí.
        Start-Transcript -Path $LogFile -Append | Out-Null
        $transcript = $true
        Write-Detalle "Registro: $LogFile"
    } catch {
        Write-Aviso "No pude abrir el registro en $LogFile"
    }

    $backendPython = Get-VenvPython $BackendVenv
    $assistantPython = Get-VenvPython $AssistantVenv

    if ($Reinstalar) {
        Write-Paso "Reinstalación explícita (-Reinstalar)"
        if (-not $SoloAsistente) { Backup-Venv $BackendVenv 'pedido con -Reinstalar'; $backendPython = $null }
        if (-not $SoloBackend) { Backup-Venv $AssistantVenv 'pedido con -Reinstalar'; $assistantPython = $null }
    }

    $systemPython = $null
    $needsBackendVenv = (-not $SoloAsistente) -and ($null -eq $backendPython)
    $needsAssistantVenv = (-not $SoloBackend) -and ($null -eq $assistantPython)
    if ($needsBackendVenv -or $needsAssistantVenv -or $Instalar) {
        Write-Paso "Buscando Python (preferido 3.$($script:PreferredMinor))"
        $systemPython = Find-SystemPython
        if ($null -eq $systemPython) {
            throw "Necesito Python 3.11 o superior (mejor 3.12). Instálalo desde https://www.python.org/downloads/ y marca 'Add python.exe to PATH', o pasa -Python RUTA."
        }
        Write-Ok "Uso Python $($systemPython.version) ($($systemPython.Label)): $($systemPython.Exe)"
        if ($systemPython.minor -ne $script:PreferredMinor) {
            Write-Aviso "No encontré Python 3.$($script:PreferredMinor); uso $($systemPython.version). El proyecto admite 3.11+, pero 3.12 es la versión probada."
        }
    }

    if ($needsBackendVenv) {
        if (Test-Path -LiteralPath $BackendVenv) { Backup-Venv $BackendVenv 'la carpeta existe pero no tiene un python válido' }
        $backendPython = New-Venv $BackendVenv $systemPython 'el backend'
    }
    if ($needsAssistantVenv) {
        if (Test-Path -LiteralPath $AssistantVenv) { Backup-Venv $AssistantVenv 'la carpeta existe pero no tiene un python válido' }
        $assistantPython = New-Venv $AssistantVenv $systemPython 'el asistente'
    }

    if ((-not $SoloAsistente) -and (-not $backendPython)) { throw "Falta el entorno del backend en $BackendVenv" }
    if ((-not $SoloBackend) -and (-not $assistantPython)) { throw "Falta el entorno del asistente en $AssistantVenv" }

    if (-not $SoloAsistente) {
        $backendInfo = Get-PythonInfo $backendPython
        if ($backendInfo -and $backendInfo.minor -ne $script:PreferredMinor) {
            Write-Aviso "El entorno del backend usa Python $($backendInfo.version); lo probado es 3.$($script:PreferredMinor)."
        }
        Write-Ok "Backend: $backendPython"
    }
    if (-not $SoloBackend) {
        $assistantInfo = Get-PythonInfo $assistantPython
        if ($assistantInfo -and $assistantInfo.minor -ne $script:PreferredMinor) {
            Write-Aviso "El entorno del asistente usa Python $($assistantInfo.version); lo probado es 3.$($script:PreferredMinor)."
        }
        Write-Ok "Asistente: $assistantPython"
    }

    Initialize-NetworkEnvironment

    # Instalar solo si hace falta: un arranque normal no toca la red.
    if (-not $SoloAsistente) {
        if ($Instalar -or (-not (Test-BackendReady $backendPython))) {
            if (-not $Instalar) { Write-Aviso "Faltan dependencias del backend; las instalo" }
            Install-BackendDependencies $backendPython
            if (-not (Test-BackendReady $backendPython)) {
                throw "El backend sigue incompleto después de instalar. Revisa $LogFile."
            }
        }
        if ($Instalar) {
            Write-Paso "Comprobando el entorno del backend (pip check)"
            & $backendPython -m pip check
            if ($LASTEXITCODE -ne 0) { Write-Aviso "'pip check' encontró conflictos; el backend puede arrancar igual." }
        }
    }
    if (-not $SoloBackend) {
        if ($Instalar -or (-not (Test-AssistantReady $assistantPython))) {
            if (-not $Instalar) { Write-Aviso "Faltan dependencias del asistente; las instalo" }
            Install-AssistantDependencies $assistantPython
            if (-not (Test-AssistantReady $assistantPython)) {
                throw "El asistente sigue incompleto después de instalar. Revisa $LogFile."
            }
        }
        if ($Instalar) {
            Write-Paso "Comprobando el entorno del asistente (pip check)"
            & $assistantPython -m pip check
            if ($LASTEXITCODE -ne 0) { Write-Aviso "'pip check' encontró conflictos; el asistente puede abrir igual." }
        }
    }

    if ($Preparar) {
        Write-Host ""
        Write-Ok "Entornos listos. Arranca con: .\arrancar.ps1"
        exit 0
    }

    # --- Arranque ------------------------------------------------------------

    $launcherArgs = @()
    if ($SoloBackend) { $launcherArgs += '--backend-only' }
    if ($SoloAsistente) { $launcherArgs += '--assistant-only' }
    if ($Url) { $launcherArgs += @('--url', $Url) }
    if ($Puerto -gt 0) { $launcherArgs += @('--port', "$Puerto") }
    if ($Clave) { $launcherArgs += @('--voice-key', $Clave) }
    if ($Empresa) { $launcherArgs += @('--company', $Empresa) }
    if (-not $SoloAsistente) { $launcherArgs += @('--backend-python', $backendPython) }
    if ((-not $SoloBackend) -and $assistantPython) { $launcherArgs += @('--assistant-python', $assistantPython) }

    $runner = if ($SoloAsistente) { $assistantPython } else { $backendPython }
    if (-not $runner) { throw "No tengo un intérprete con el que arrancar el producto." }
    if (-not (Test-Path -LiteralPath $runner)) { throw "El intérprete $runner no existe." }

    $puertoTexto = if ($Puerto -gt 0) { "$Puerto" } else { 'automático (8000 si está libre)' }
    Write-Paso "Arrancando la fábrica y el asistente (puerto $puertoTexto; Ctrl+C para parar los dos)"
    & $runner -u $Launcher @launcherArgs
    $script:ExitCode = $LASTEXITCODE
    if ($script:ExitCode -ne 0) {
        Write-Host ""
        Write-Fallo "El producto terminó con código $($script:ExitCode)."
        Write-Detalle "Registro completo: $LogFile"
    }
} catch {
    Write-Host ""
    Write-Fallo $_.Exception.Message
    if ($_.ScriptStackTrace) { Write-Detalle $_.ScriptStackTrace }
    Write-Detalle "Registro completo: $LogFile"
    $script:ExitCode = 1
} finally {
    if ($transcript) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

exit $script:ExitCode
