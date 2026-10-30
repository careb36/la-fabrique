# Start the Fabrique workspace daemon on this computer (Windows).
#
# The daemon is what lets the agents work in the folders where you cloned your
# GitHub/GitLab projects: it lists folders for the picker, checks a project,
# writes the agents' files and runs commands there. It connects to the NATS
# server of the Docker stack (nats://localhost:4222, override with $env:NATS_URL)
# and keeps retrying until it is up.
#
# If scripts are blocked on this machine, run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\start-daemon.ps1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$DaemonDir = Join-Path $Root 'vscode-daemon'
$Venv = Join-Path $DaemonDir '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $Venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $Venv
    } else {
        throw 'Python 3.9 or newer is required: install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH").'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment.' }
}

& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $DaemonDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the daemon requirements.' }

if (-not $env:NATS_URL) { $env:NATS_URL = 'nats://localhost:4222' }
& $VenvPython (Join-Path $DaemonDir 'daemon.py')
