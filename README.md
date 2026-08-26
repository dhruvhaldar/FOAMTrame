<p align="center">
  <img src="./static/icons/logo.svg" alt="FOAMTrame logo" width="88" height="88">
</p>

<h1 align="center">FOAMTrame</h1>

<p align="center">
  A responsive, browser-based OpenFOAM workspace built with
  <a href="https://kitware.github.io/trame/">Trame</a>,
  <a href="https://vtk.org/">VTK</a>, and
  <a href="https://www.docker.com/">Docker</a>.
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-0c6e87?logo=python&logoColor=white"></a>
  <a href="https://github.com/dhruvhaldar/FOAMTrame/actions/workflows/ci.yml"><img alt="CodeAudit status" src="https://img.shields.io/github/actions/workflow/status/dhruvhaldar/FOAMTrame/ci.yml?branch=main&label=CodeAudit&logo=githubactions&logoColor=white"></a>
  <a href="https://github.com/dhruvhaldar/FOAMTrame/actions/workflows/ci.yml"><img alt="Ruff status" src="https://img.shields.io/github/actions/workflow/status/dhruvhaldar/FOAMTrame/ci.yml?branch=main&label=Ruff&logo=ruff&logoColor=white"></a>
  <a href="https://docs.astral.sh/uv/"><img alt="uv locked" src="https://img.shields.io/badge/uv-locked-DE5FE9?logo=uv&logoColor=white"></a>
  <a href="https://kitware.github.io/trame/"><img alt="Trame 3" src="https://img.shields.io/badge/Trame-3-069ab5"></a>
  <a href="https://www.docker.com/"><img alt="Docker required" src="https://img.shields.io/badge/Docker-required-2496ED?logo=docker&logoColor=white"></a>
  <a href="#offline-installation"><img alt="Runs offline" src="https://img.shields.io/badge/Runs_offline-supported-069ab5"></a>
  <a href="./LICENSE"><img alt="GNU GPLv3" src="https://img.shields.io/badge/License-GPLv3-0c6e87"></a>
</p>

FOAMTrame brings case selection, tutorial import, OpenFOAM command execution, live logs, run history, plots, and VTK post-processing into one glass-styled web interface. OpenFOAM operations run through a configured Docker image, while VTK rendering and data processing remain server-side.

## Table of contents

- [Start here](#start-here)
- [Features](#features)
- [Application workflow](#application-workflow)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running FOAMTrame](#running-foamtrame)
- [Using the application](#using-the-application)
- [App-state persistence](#app-state-persistence)
- [Backup and restore](#backup-and-restore)
- [Supported datasets](#supported-datasets)
- [Optional Flask API](#optional-flask-api)
- [Project structure](#project-structure)
- [Caching and performance](#caching-and-performance)
- [Development checks](#development-checks)
- [Documentation maintenance](#documentation-maintenance)
- [Extension roadmap](#extension-roadmap)
- [Contributing](#contributing)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [License](#license)

## Start here

Choose the shortest route for what you want to do. Every command in this README
is intended to be run from the repository root.

| I want to… | Start with | Then read |
| --- | --- | --- |
| Use FOAMTrame on Windows | [Windows installation](#windows-powershell) | [Running FOAMTrame](#running-foamtrame) |
| Use FOAMTrame on Linux | [Linux installation](#linux) | [Using the application](#using-the-application) |
| Run an unattended installation | [Automated silent-install examples](#automated-silent-install-examples) | [Runtime configuration](#runtime-configuration) |
| Develop or review a change | [Project structure](#project-structure) | [Development checks](#development-checks) |
| Diagnose a problem | [Troubleshooting](#troubleshooting) | [Security notes](#security-notes) |
| Extend the product | [Extension roadmap](#extension-roadmap) | [Contributing](#contributing) |

Quick start on Windows:

```powershell
.\install.ps1
.\start.ps1
```

Quick start on Linux:

```bash
./install.sh
./start.sh
```

The default URL is [http://localhost:8087](http://localhost:8087). Docker may be
unavailable while the UI starts, but tutorial import and OpenFOAM execution need
a reachable Docker daemon and configured image.

## Features

### Setup and case management

- Verifies the Trame server, Docker daemon, and configured OpenFOAM image.
- Detects `WM_PROJECT_VERSION` from the configured Docker image and displays it
  in the always-visible Setup sidebar footer, with an explicitly labelled
  configured-version fallback when the container runtime cannot be inspected.
- Shows a dynamic `Build YYYY-MM-DD` value in that footer. Packaged and CI builds
  may set `FOAMTRAME_BUILD_DATE`; local source runs fall back to the `app.py`
  modification date.
- Scans a configurable case-root directory and restores the last active case.
- Creates a blank OpenFOAM case with `0`, `constant`, and `system` directories.
- Discovers official tutorials inside the Docker image.
- Provides searchable tutorial browsing and imports a selected tutorial into the local workspace.
- Disables active-case selection with a clear empty state when no cases exist.

Implementation: [tabs/setup_tab.py](./tabs/setup_tab.py)

### Geometry

- Opens on **Case** when an active case exists and renders every supported surface
  under that case's `constant/triSurface` directory. When no supported triSurface
  files exist, it falls back to the case's `constant/geometry` directory.
- Falls back to **Custom** when no case is selected; case-dependent **Case** and
  **Library** controls remain visible but disabled.
- Clears the case render before switching to a session-only custom VTK or surface
  dataset.
- Browses `$FOAM_TUTORIALS/resources/geometry` inside the configured OpenFOAM
  image and safely imports a selected resource into the active case.
- Displays dataset type, aggregate point count, and aggregate cell count.
- Uses server-side VTK rendering with camera reset and interactive controls.
- Persists the preferred geometry mode and library selection in SQLite and the
  portable JSON backup. Case geometry and uploaded datasets remain on disk and
  are not embedded in the database or backup.

Implementation: [tabs/geometry_tab.py](./tabs/geometry_tab.py) and
[backend/geometry/library.py](./backend/geometry/library.py)

### Meshing

- The Meshing navigation surface is currently reserved for future meshing tools.
- OpenFOAM meshing commands such as `blockMesh` are available from **Run/Log**.

Placeholder: [tabs/meshing_tab.py](./tabs/meshing_tab.py)

### Run and logs

- Detects logical and physical CPU counts.
- Configures process count and reports decomposition status.
- Scans the active case and configured Docker image to expose only validated
  application actions while keeping unavailable commands visible with their
  exact missing prerequisite.
- Prefers a case-provided `Allrun`; otherwise offers a reviewable guided sequence
  containing only confidently detected preprocessing, meshing, and solver steps.
- Keeps WORKFLOW, DETECTED COMMANDS, and CLEANUP visible in the wider Run/Log
  sidebar. The compact command grid remains directly actionable, while the
  detailed capability list and unavailable reasons open from **Available actions**.
- Derives the solver application and optional solver module from
  `system/controlDict` instead of assuming `simpleFoam` or `pimpleFoam`.
- Detects `surfaceFeatureExtract`, `blockMesh`, `snappyHexMesh`, `topoSet`,
  `setFields`, `decomposePar`, `reconstructPar`, and `foamToVTK` from their
  dictionaries, decomposition directories, result times, and Docker executables.
- Requires confirmation before `Allclean` and provides a separate safe-clean
  preview limited to detected time results, processor directories,
  `postProcessing`, `VTK`, and `log.*` files. The initial `0` directory and
  `constant/polyMesh` are preserved.
- Streams console output and supports stopping the active process.
- Archives FOAMTrame console output separately from case-owned solver logs. A
  case-provided `Allrun` remains responsible for `log.foamRun`, so launching or
  observing a run never truncates an existing residual log.
- Recognizes OpenFOAM's “already run” output. If every `Allrun` stage is skipped,
  records the run as **Skipped**, uses a warning status instead of success, and
  shows a dismissible warning notification with reviewed cleanup guidance. Partial
  skips retain **Completed** status but are identified in both the console and an
  informational notification. Cleanup choices are emphasized, while safely escaped
  console output uses distinct command, information, warning, error, and ordinary
  output colors. Existing results are never deleted automatically.
- Accepts additional validated runs while a simulation is active, executes them
  one at a time in FIFO order, and allows waiting jobs to be cancelled or cleared.
  Each submission retains the case and runtime configuration selected when it was
  queued.
- Retains up to 100 indexed run-history records in the application database.

Implementation: [tabs/run_log_tab.py](./tabs/run_log_tab.py), the dependency-free
FIFO worker in [backend/simulation_queue.py](./backend/simulation_queue.py), and
the shared, fixed-ID action service in
[backend/case/capabilities.py](./backend/case/capabilities.py). UI controls and
future chatbot tools should resolve actions through this service rather than
submitting arbitrary shell strings.

### Plots

- Detects running simulations automatically, streams live updates, and serves
  completed results from the synchronized cache without a manual refresh.
- Selects scalar fields and renders scalar, velocity-magnitude, velocity-component,
  and residual charts.
- Switches between glass, white, black, and grey plot backgrounds with
  contrast-aware palettes.
- Supports Helvetica Neue-style (bundled TeX Gyre Heros), bundled Roboto, Times
  New Roman-style (bundled Liberation Serif), and Arial typography plus no logo,
  the FOAMFlask logo, or a custom image.
- Maximizes any plot while keeping the remaining charts available in a responsive
  sidebar.
- Exports each chart as a publication-friendly PNG with a consistent white paper
  background, regardless of the selected on-screen theme.
- Persists plot appearance and logo preferences in the unified app state so they
  participate in JSON backup and restore.

Implementation: [tabs/plots_tab.py](./tabs/plots_tab.py)

### Post-processing

- Reads VTK XML and legacy datasets plus common surface formats.
- Slices along the X, Y, or Z axis.
- Clips using plane, sphere, or box controls.
- Colours data using point or cell scalar arrays.
- Applies translation, rotation, and scale transforms.
- Shows adjustable translucent source context.
- Creates streamlines from available vector arrays.

Implementation: [tabs/visualizer_tab.py](./tabs/visualizer_tab.py) and
[backend/post/postprocessor.py](./backend/post/postprocessor.py)

### Settings

- Downloads case configuration, plot preferences, security preferences, and run
  history as one versioned JSON backup.
- Validates uploaded backups before enabling restore.
- Applies restored configuration and history transactionally to SQLite and the live Trame state.
- Provides disabled-by-default, opt-in network binding, CORS, response-header,
  request-size, WebSocket-size, and companion-API-key controls. The ordinary
  server listener remains loopback-only unless explicitly changed.

Implementation: [tabs/settings_tab.py](./tabs/settings_tab.py) and [app_state.py](./app_state.py). Database schema and transactions are implemented in [database.py](./database.py).

### Documentation

- Reads this `README.md` directly from the repository; there is no second copy to
  become stale.
- Splits level-two headings into a persistent, keyboard-accessible section list in
  the drawer; all section names remain discoverable without a dropdown.
- Renders headings, lists, tables, links, quotes, and fenced code blocks locally,
  without a CDN or browser-side Markdown dependency.
- Converts the supported fenced Mermaid `flowchart LR` subset into accessible
  inline SVG and safely displays unsupported Mermaid syntax as escaped code.
- Sanitizes README content before it reaches Vue and provides **Reload README** for
  reviewing edits without restarting FOAMTrame.

Implementation: [tabs/documentation_tab.py](./tabs/documentation_tab.py)

## Application workflow

1. Open **Setup** and wait for both health checks.
2. Select an existing case, create a blank case, or import an OpenFOAM tutorial.
3. Inspect available case geometry in **Geometry**.
4. Run meshing, solver, conversion, or case scripts from **Run/Log**.
5. Monitor solver data under **Plots**.
6. Inspect VTK results under **Post**.
7. Consult the in-app **Documentation** page for setup, operating, and development
   guidance sourced from this README.
8. Download periodic state backups from the gear-shaped **Settings** tab.

## Architecture

```mermaid
flowchart LR
    Browser["Browser UI<br>Vue 2 + Vuetify"]
    Trame["Trame server<br>app.py :8087"]
    Services["Application services<br>shared human/agent commands"]
    State["foamtrame.db<br>SQLite + WAL"]
    Backup["Portable JSON<br>backup / restore"]
    Agent["Future chatbot<br>typed tool calls"]
    Docker["Docker daemon<br>OpenFOAM image"]
    Cases["Case workspace<br>tutorial_cases/"]
    VTK["VTK pipeline<br>geometry + post-processing"]

    Browser <-->|"wslink state and actions"| Trame
    Trame --> Services
    Agent -->|"validated actions"| Services
    Services <-->|"transactions"| State
    State <-->|"export / restore"| Backup
    Trame <-->|"container execution"| Docker
    Docker <-->|"mounted case data"| Cases
    Trame <-->|"scan/import/run"| Cases
    Trame <-->|"server-side rendering"| VTK
```

The primary entry point is [app.py](./app.py). It composes each tab under [tabs/](./tabs), connects backend managers under [backend/](./backend), and starts Trame on port `8087`.

### Database decision

FOAMTrame uses [SQLite](https://www.sqlite.org/) as its operational database. This is deliberate: the current application is local, single-process software, so an embedded database preserves simple installation and portable project state without requiring a database server, credentials, or another container. WAL mode, foreign keys, a busy timeout, and short-lived per-operation connections make background simulation-thread access predictable.

The database boundary lives in [database.py](./database.py), while [app_state.py](./app_state.py) retains the stable application-facing API. If FOAMTrame later becomes a hosted multi-user service or runs independent workers, that boundary should move to PostgreSQL rather than exposing SQL throughout the
UI and backend modules.

The planned chatbot should not automate browser clicks. Buttons and chatbot tools should invoke the same application-service commands. The `automation_actions` table is reserved for durable parameters, confirmation state, execution status, results, errors, and audit history; destructive or expensive commands can therefore require explicit confirmation before execution.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or another
  reachable Docker daemon
- A modern browser with WebSocket support
- Enough memory for the selected VTK dataset and OpenFOAM container workload

Direct dependencies are declared in [pyproject.toml](./pyproject.toml), and the
complete cross-platform environment is reproducibly pinned in
[uv.lock](./uv.lock):

- Trame 3 and Trame-Vuetify 3
- VTK 9.3+
- Docker SDK for Python 7.1+
- Flask 3 and Flask-Compress
- Requests and psutil

## Installation

Clone or download the repository. The supported installers use `uv sync` to create
the project `.venv` from `uv.lock`, initialize SQLite, run machine-readable
diagnostics, and preserve any existing database or JSON migration data. A global
Python and `uv` installations are optional on Windows and Linux x86_64. The
platform installer first uses an existing CPython 3.12 interpreter when one is
available through PATH (or the Windows Python launcher). Otherwise, it verifies
and extracts bundled CPython 3.12.13. It then prefers a system `uv`, falling back
to the verified bundled `uv 0.10.12`. Both local runtimes live only in the ignored
`.foamtrame-tools/` directory, require no administrator privileges, and do not
modify PATH, the Windows registry, or existing Python installations.

### Windows PowerShell

```powershell
.\install.ps1
```

Install development/test dependencies as well:

```powershell
.\install.ps1 --dev
```

Choose a specific Trame port, or let the installer select a free one:

```powershell
.\install.ps1 --port 5087
.\install.ps1 --auto-port
```

Run a fully unattended installation with no console progress:

```powershell
.\install.ps1 --silent
# Unattended and automatically select a free port:
.\install.ps1 --silent --auto-port
```

### Linux

```bash
bash ./install.sh
# Include test tooling:
bash ./install.sh --dev
```

```bash
bash ./install.sh --port 5087
bash ./install.sh --auto-port
```

```bash
# Fully unattended; command output is recorded instead of printed:
bash ./install.sh --silent
bash ./install.sh --silent --auto-port
```

Both installers accept `--help`, `--dev`, `--skip-docker-check`, `--port`,
`--auto-port`, and `--silent` (also `--quiet` or `-q`). The shared implementation is
[install.py](./install.py), so Windows and Linux follow the same installation
logic.

When neither port option is supplied, the installer uses `8087`. It verifies
and reserves the selected port before creating the virtual environment or
installing packages. If `8087` (or an explicitly requested port) is unavailable,
installation stops with instructions to use `--port PORT` or `--auto-port`.
The successful selection is stored locally in `.foamtrame-port` and used by the
start scripts.

Silent mode is non-interactive: subprocess stdin and `uv` progress output are
disabled, and detailed command output is appended to
`logs/YYYYMMDD/install.log`. A successful silent install exits with code `0`
without console output. Failures return a nonzero code and print only the log
location. Silent mode does not weaken port validation: without a port option it
still requires `8087` to be free; use `--port PORT` or `--auto-port` when that is
unsuitable.

### Offline installation

The repository includes official compressed CPython and `uv` runtimes, published
checksums, and licenses for Windows x86_64 and Linux x86_64 (GNU libc). Therefore
an offline computer does not need Python or `uv` preinstalled. Compatible system
installations are preferred when available, while verified project-local copies
are installed automatically otherwise. Windows requires its built-in `tar`
utility; the standalone Python build also follows the standard CPython requirement
for the Microsoft Visual C++ runtime. Linux requires GNU libc 2.17 or newer,
`tar`, and either `sha256sum` or `shasum`.

Bundling Python and `uv` does not bundle VTK or the other packages referenced by
`uv.lock`. A first-time installation on a completely offline computer must also be
provided with those platform-specific packages, an already synchronized `.venv`,
or a populated `uv` cache. Docker-based OpenFOAM operations additionally require
Docker and the configured image to already be installed locally. Once these assets
are present, `start.ps1` and `start.sh` are independent of global Python and `uv`
installations.

### Automated silent-install examples

Invoke the Windows installer directly from deployment software without loading a
user profile or opening an interactive shell:

```powershell
# Windows PowerShell 5.1
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\install.ps1 --silent --auto-port

# PowerShell 7+
pwsh -NoProfile -NonInteractive -File .\install.ps1 --silent --auto-port
```

Use the documented default port (`8087`) and fail if it is occupied:

```powershell
# Windows PowerShell
.\install.ps1 --silent
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

```bash
# Linux shell
./install.sh --silent
```

Use a fixed deployment port:

```powershell
.\install.ps1 --silent --port 5087
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

```bash
./install.sh --silent --port 5087
```

Automatically reserve a free port and read the selected value after installation:

```powershell
.\install.ps1 --silent --auto-port
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$FoamTramePort = (Get-Content -LiteralPath .\.foamtrame-port -Raw).Trim()
Write-Output "FOAMTrame installed on port $FoamTramePort"
```

```bash
./install.sh --silent --auto-port
FOAMTRAME_PORT="$(<.foamtrame-port)"
printf 'FOAMTrame installed on port %s\n' "$FOAMTRAME_PORT"
```

Surface the dated installer log when an unattended installation fails:

```powershell
.\install.ps1 --silent --auto-port
$InstallExitCode = $LASTEXITCODE
if ($InstallExitCode -ne 0) {
    $LogFile = Join-Path (Join-Path .\logs (Get-Date -Format yyyyMMdd)) install.log
    if (Test-Path -LiteralPath $LogFile) { Get-Content -LiteralPath $LogFile -Tail 100 }
    exit $InstallExitCode
}
```

```bash
if ! ./install.sh --silent --auto-port; then
  log_file="logs/$(date +%Y%m%d)/install.log"
  [[ -f "$log_file" ]] && tail -n 100 "$log_file"
  exit 1
fi
```

Example GitHub Actions steps:

```yaml
- name: Install FOAMTrame unattended
  shell: bash
  run: ./install.sh --silent --auto-port

- name: Publish selected port to later steps
  shell: bash
  run: echo "FOAMTRAME_PORT=$(cat .foamtrame-port)" >> "$GITHUB_ENV"
```

Make sure Docker is running and pull the default image if it is not already available:

```bash
docker pull haldardhruv/ubuntu_noble_openfoam:v12
```

The image, OpenFOAM version, and case-root directory can be changed later under **Setup → Advanced Settings**.

## Running FOAMTrame

Use the platform launcher after installation:

```powershell
.\start.ps1
```

```bash
./start.sh
```

The launchers call [run.py](./run.py), forward termination signals, use the
installed interpreter, and keep the working directory deterministic. The
installer prints the selected URL; with no port option it is
[http://localhost:8087](http://localhost:8087).

Trame's standard server arguments remain supported:

```bash
./start.sh --port 8090 --host 127.0.0.1
```

Run diagnostics or initialize/upgrade the database independently:

```bash
uv run --locked python manage.py doctor
uv run --locked python manage.py init-db
```

### Runtime configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `FOAMTRAME_DATA_DIR` | Repository directory | Database and legacy migration data |
| `FOAMTRAME_DATABASE_PATH` | `<data-dir>/foamtrame.db` | Explicit SQLite database path |
| `FOAMTRAME_LOG_DIR` | `<data-dir>/logs` | Base directory for date-grouped application logs |
| `FOAMTRAME_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `FOAMTRAME_FRAMEWORK_LOG_LEVEL` | `WARNING` | Trame/wslink verbosity; set to `INFO` only for framework diagnostics |
| `FOAMTRAME_PORT` | Installer selection (`8087` when skipped) | Override the installed port when `--port` is omitted |

Operational logs are grouped by the local start date using `YYYYMMDD` folders.
Structured application logs rotate at 5 MB with three retained backups under
`logs/YYYYMMDD/foamtrame.log`. Every start-script session is also appended
verbatim to `logs/YYYYMMDD/run.log`, including child stdout, stderr, the invoked
command, timestamps, and exit code. Silent installer output uses
`logs/YYYYMMDD/install.log`. CLI `--host` and `--port` override runtime defaults. When `--host` is
omitted, the Trame host comes from **Settings → Security** (`127.0.0.1` by default).

### Load a dataset at startup

Use `--data` with a server-local supported dataset:

```bash
./start.sh --data /path/to/model.vtu
```

## Using the application

### Create a blank case

1. Open **Setup**.
2. Select **Create Blank Case**.
3. Enter a case name.
4. Select **Create Case**.

The case is created below the configured `CASE_ROOT` and becomes active.

### Import an OpenFOAM tutorial

1. Wait for **Docker integration ready**.
2. Select **Import Tutorial**.
3. Search the tutorial list.
4. Select a tutorial source.
5. Select **Import Tutorial**.

Tutorial discovery and import use the configured Docker image. The tutorial is copied into the local case workspace rather than edited inside the image.

### Run a case

1. Choose an active case under **Setup**.
2. Open **Run/Log**.
3. Set the desired process count if parallel execution is required.
4. Select a workflow or detected command from the drawer. Use **Available actions**
   to review the complete capability list and unavailable reasons.
5. Follow output in **Console Log Output**.
6. If `Allrun` is reported as **Skipped**, review **Allclean** or **Safe Clean
   Generated Outputs** before rerunning. Cleanup is always explicit and confirmed.

Run history records command, case, status, timestamps, and duration. The main
status chip and run history distinguish completed, skipped, failed, and running
states using matching success, warning, error, and progress treatments.

## App-state persistence

FOAMTrame stores operational application state in one embedded database:

```text
foamtrame.db
```

The database and its WAL sidecar files are excluded by [.gitignore](./.gitignore) because they may contain machine-specific paths and local run history. SQLite stores configuration and simulation runs in relational tables; case folders, OpenFOAM result files, and large logs remain in the case workspace and are referenced by path rather than copied into database blobs.

JSON is now an interchange format only. A portable backup schema example remains available at [app_state.json.example](./app_state.json.example):

```json
{
  "version": 3,
  "case_config": {
    "CASE_ROOT": "/path/to/tutorial_cases",
    "DOCKER_IMAGE": "haldardhruv/ubuntu_noble_openfoam:v12",
    "OPENFOAM_VERSION": "12",
    "ACTIVE_CASE": "aerofoilNACA0012"
  },
  "geometry_preferences": {
    "preferred_mode": "case",
    "library_selection": ""
  },
  "run_history": [],
  "security_preferences": {
    "security_enabled": false,
    "bind_mode": "loopback",
    "cors_mode": "same_origin",
    "cors_origin": "",
    "security_headers": true,
    "api_key_enabled": false,
    "api_key_hash": "",
    "max_request_mb": 2,
    "websocket_max_message_mb": 4,
    "session_timeout_enabled": false,
    "session_timeout_minutes": 30
  }
}
```

Database updates use transactions. On first launch, an existing `app_state.json` is imported into SQLite; older `case_config.json` and `run_history.json` files are also supported as migration sources. Legacy files are left untouched so migration is recoverable, but SQLite becomes the source of truth once initialized.

The initial schema contains:

| Table | Responsibility |
| --- | --- |
| `schema_metadata` | Schema version and initialization markers |
| `app_config` | Typed JSON values for case root, active case, Docker image, and OpenFOAM version |
| `simulation_runs` | Indexed command, case, status, timestamps, duration, and complete compatible run record |
| `app_preferences` | Plot typography, background, and logo preferences |
| `geometry_preferences` | Preferred Geometry subpage and library selection |
| `security_preferences` | Validated network, CORS, header, size-limit, session-timeout, and API-key policy |
| `cases` | Relational case catalogue ready for workspace synchronization |
| `automation_actions` | Future chatbot/automation command queue and audit trail |

## Backup and restore

### Backup

1. Open the gear-shaped **Settings** tab.
2. Select **Backup JSON**.
3. Store `foamtrame-app-state.json` somewhere safe.

### Restore

1. Open **Settings**.
2. Choose a previously downloaded `.json` backup.
3. Wait for validation to succeed.
4. Select **Restore App State**.

Restore replaces the persisted case configuration, plot, geometry, and security
preferences, and run history. It does **not** copy case directories, imported case
geometry, simulation results, uploaded VTK datasets, or Docker images. If a backup references a case root that
does not exist on the new machine, update **Advanced Settings** after restoring.
Security preferences containing an API-key hash are transferable, but the original
plain-text key cannot be recovered from a backup.

## Supported datasets

| Extension | Dataset or surface type |
| --- | --- |
| `.vtk` | VTK legacy dataset |
| `.vtu` | XML unstructured grid |
| `.vtp` | XML polydata |
| `.vti` | XML image data |
| `.vtr` | XML rectilinear grid |
| `.vts` | XML structured grid |
| `.ply` | Polygon surface |
| `.stl` | Triangulated surface |
| `.obj` | Wavefront surface |

Parallel XML collections such as `.pvtu` are not accepted through the single-file browser uploader because their referenced piece files must travel together.

## Optional Flask API

[flask_server.py](./flask_server.py) exposes a companion HTTP API on port `5000`. It is not required for the main Trame UI.

Start it separately when API access is needed:

```bash
python flask_server.py
```

When API-key protection is enabled in **Settings → Security**, mutating requests
(`POST`, `PUT`, `PATCH`, and `DELETE`) must include the generated key as
`X-FOAMTrame-API-Key`. Read-only requests remain available, subject to the selected
CORS policy. The companion API remains loopback-bound by default.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/get_case_root` | Read the configured case root |
| `GET` | `/get_active_case` | Read the active case |
| `POST` | `/set_active_case` | Change the active case |
| `POST` | `/set_case` | Update case selection data |
| `GET` | `/get_docker_config` | Read Docker/OpenFOAM configuration |
| `POST` | `/set_docker_config` | Update Docker/OpenFOAM configuration |
| `GET` | `/api/cases/list` | List local cases |
| `POST` | `/api/case/create` | Create a blank case |
| `GET` | `/api/tutorials` | Discover available tutorials |
| `POST` | `/load_tutorial` | Import a tutorial |
| `GET` | `/api/case/resolve_vtk` | Resolve the newest supported case dataset |
| `GET` | `/api/startup_status` | Read backend startup status |

## Project structure

```text
.
├── app.py                    # Main Trame application and global visual system
├── app_state.py              # State API, legacy migration, JSON backup/restore
├── database.py               # SQLite schema, transactions, and repository boundary
├── runtime.py                # Runtime paths, logging, and preflight diagnostics
├── manage.py                 # Doctor and database administration commands
├── install.py                # Shared cross-platform installer implementation
├── install.ps1 / install.sh  # Windows and Linux installer entry points
├── start.ps1 / start.sh      # Locked uv-environment launchers
├── app_state.json.example    # Portable state schema example
├── flask_server.py           # Optional companion HTTP API
├── run.py                    # Process wrapper and signal forwarding
├── python_bootstrap.ps1/.sh  # System/bundled CPython selection and extraction
├── uv_bootstrap.py           # Verified system/bundled uv selection and extraction
├── pyproject.toml            # Project metadata and direct dependencies
├── uv.lock                   # Reproducible dependency lockfile
├── vendor/uv/                # Offline uv archives, checksums, and upstream licenses
├── vendor/python/            # Offline CPython archives, checksums, and licenses
├── tests/
│   ├── integration/          # Database, migration, rollback, concurrency
│   └── smoke/                # One complete server availability test
├── .github/workflows/ci.yml  # Windows/Linux automated verification
├── backend/
│   ├── case/                 # Case-management helpers
│   ├── geometry/             # Geometry managers and visualization
│   ├── mesh/                 # Mesh readers and utilities
│   ├── meshing/              # OpenFOAM meshing helpers
│   ├── plots/                # Realtime/cached plotting backend
│   ├── post/                 # VTK post-processing backend
│   └── visualization/        # Shared visualization abstractions
├── static/
│   └── icons/                # FOAMTrame, Docker, and Trame assets
└── tabs/
    ├── setup_tab.py
    ├── geometry_tab.py
    ├── meshing_tab.py
    ├── run_log_tab.py
    ├── plots_tab.py
    ├── visualizer_tab.py
    ├── documentation_tab.py
    └── settings_tab.py
```

Follow the links below for the principal implementation surfaces:

- [Main application](./app.py)
- [State persistence](./app_state.py)
- [Database repository and schema](./database.py)
- [UI tabs](./tabs)
- [Backend modules](./backend)
- [Static assets](./static)

## Caching and performance

FOAMTrame uses [Cachebox](https://github.com/awolverp/cachebox) 6.1 for
thread-safe, bounded in-memory memoization. LRU caches cover repeated
`controlDict` metadata reads, safe-clean directory scans, OpenFOAM field-header
lookups, directory scans, compiled variable patterns, plot logos, and generated
geometry/mesh views. Repeated Docker executable probes use a five-second TTL to
coalesce rapid rescans without masking runtime changes for long. File-backed
keys include modification time (and file size where relevant), so a changed
case or asset naturally produces a cache miss.
Large live-result caches remain specialized and append-aware: residual logs and
time series reuse stable parsed history while reading only newly appended data.

Cache capacities are deliberately bounded. High-cardinality field and file
lookups retain up to 4,096 entries, directory scans up to 1,024, and rendered
assets use smaller workload-specific limits. Selecting a different case or
requesting a plot refresh continues to clear the relevant case-scoped entries.

The reproducible microbenchmark compares the uncached implementation with a
warmed normal cache hit while retaining the same filesystem signature checks:

```bash
uv run --locked python benchmarks/benchmark_cachebox.py
```

On Windows with CPython 3.13.7, using the default 2,000 iterations and the
median of seven rounds, the implementation measured:

| Operation | Uncached (µs/call) | Cached (µs/call) | Speedup |
|---|---:|---:|---:|
| `controlDict` solver metadata | 486.36 | 28.90 | 16.8× |
| Safe-clean scan (200 outputs) | 6,254.79 | 10.62 | 588.7× |

These are local microbenchmarks, not end-to-end UI latency guarantees. Results
vary with filesystem, antivirus, hardware, case size, and cache warmth; use the
included script to measure the target machine.

## Development checks

Install the development profile first:

```bash
./install.sh --dev
# Windows: .\install.ps1 --dev
```

Compile the main Python modules after making changes:

```bash
uv run --locked python -m py_compile \
  app.py app_state.py database.py flask_server.py \
  tabs/setup_tab.py tabs/run_log_tab.py tabs/settings_tab.py
```

Lint and type-check the Python code with the locked Ruff and `ty` versions:

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
```

Ruff enforces the core Pyflakes and critical pycodestyle lint rules plus its
deterministic formatter. Run `uv run --locked ruff format .` to apply formatting
before committing. `ty` targets every supported platform and checks application
code, tests, and benchmarks while excluding scratch diagnostics. A narrow `ty`
override covers cachebox decorator-generated methods, and optional PyVista and
native accelerator imports remain valid when those components are not installed.

On Python 3.11 or newer, run the CodeAudit SAST gate as well. Reviewed false
positives use inline `# nosec` comments with a reason; new medium, high, or
critical findings fail the command and CI:

```bash
uv run --locked python scripts/codeaudit_gate.py .
```

Validate database initialization and the persisted state schema:

```bash
uv run --locked python -c "import app_state; from database import database; state = app_state.load_app_state(); print(database.path, state['version'], state.keys())"
```

Run the integration suite:

```bash
uv run --locked python -m unittest discover -s tests/integration -v
# or
uv run --locked pytest -m integration
```

Run the cache benchmark after changing cache keys, capacities, or invalidation:

```bash
uv run --locked python benchmarks/benchmark_cachebox.py
```

Run the single end-to-end server smoke test:

```bash
uv run --locked python -m unittest tests.smoke.test_server_starts -v
# or
uv run --locked pytest -m smoke
```

The smoke test starts the complete application on an ephemeral loopback port, waits for an HTTP 200 HTML response, and always terminates the child process. It skips only when Trame/VTK are absent from the selected interpreter. The [CI workflow](./.github/workflows/ci.yml) installs the full runtime and runs all tests on both Windows and Linux.

For UI changes, check at least one desktop and one constrained viewport. Confirm that navigation remains reachable, cards do not overflow, and controls retain visible focus states.

## Documentation maintenance

This README is both the repository landing page and the source for FOAMTrame's
in-app **Documentation** page. Keep it useful to both audiences:

1. Add major topics as level-two (`##`) sections. Each one automatically becomes
   a selectable in-app section.
2. Use level-three headings for tasks within a topic and keep heading names unique
   so anchor links remain predictable.
3. Put the outcome and common command first, followed by constraints, alternatives,
   and implementation detail.
4. Prefer relative repository links and fenced code blocks with a language label.
   Use fenced `mermaid` with `flowchart LR` for architecture diagrams; the in-app
   renderer converts the supported node-and-edge subset into accessible inline SVG.
5. Update the table of contents, relevant feature description, project tree, and
   troubleshooting guidance when a change affects them.
6. Keep machine-local paths, credentials, API keys, databases, logs, and case
   results out of examples.

The in-app renderer deliberately supports a stable Markdown subset: headings,
paragraphs, emphasis, links, ordered and unordered lists, blockquotes, tables,
fenced code, and left-to-right Mermaid flowcharts. Unsupported or malformed
Mermaid syntax is displayed safely as code instead of being executed. Raw HTML is
not trusted in the application view. Repository-hosted Markdown can still use
presentation HTML for badges and the centered logo.

When a topic grows large enough to obscure the main workflow, add a concise
summary here and move deep reference material into `docs/<topic>.md`. Link the new
guide from **Start here**, the table of contents, and the relevant feature section.
This keeps the README comprehensive as an index while allowing future material to
grow without turning one page into an unstructured manual.

## Extension roadmap

The current service boundaries are intended to support future additions without
duplicating validation or coupling new surfaces directly to UI buttons.

| Addition | Preferred extension point | Required safeguards |
| --- | --- | --- |
| Meshing workflows | `backend/meshing/` plus `tabs/meshing_tab.py` | Resolve fixed action IDs and verify case prerequisites |
| New case commands | `backend/case/capabilities.py` | Keep unavailable actions visible with reasons; never accept arbitrary shell text |
| Plot types and parsers | `backend/plots/realtime_plots.py` and `tabs/plots_tab.py` | Preserve incremental reads, non-overlap layout, and white PNG export |
| Dataset readers or filters | `backend/post/` and the owning UI tab | Keep processing server-side and document accepted extensions |
| Automation or chatbot tools | Shared application/service actions | Require typed parameters, confirmation where needed, and durable audit state |
| Persistence fields | `database.py`, `app_state.py`, and backup normalization | Add a migration, preserve transactions, and update `app_state.json.example` |
| Optional security controls | `security.py` and `tabs/settings_tab.py` | Remain disabled by default and validate restored values before use |
| Additional documentation | A new `##` section or focused `docs/*.md` guide | Update navigation links and keep the in-app subset readable |

These are extension options, not promises of schedule or scope. New work should
follow the same local-first behavior: Docker-dependent features may degrade, but
the application shell and documentation should continue to start.

## Contributing

Before changing code, read [AGENTS.md](./AGENTS.md), inspect the nearest tests, and
preserve unrelated workspace changes. Keep each change focused and compatible with
Python 3.10 or newer.

A contribution is ready for review when it includes:

- the user-visible implementation and proportionate automated tests;
- documentation for changed behavior, configuration, or supported formats;
- schema and portable-backup updates for persistence changes;
- focused verification results and, for UI changes, desktop plus constrained-width
  visual checks;
- no machine-local databases, logs, ports, virtual environments, case results, or
  credentials.

Use the commands under [Development checks](#development-checks). A pull request or
handoff should summarize behavior, compatibility or migration impact, and the exact
commands that passed.

## Troubleshooting

### Docker integration is not ready

- Start Docker Desktop or the Docker daemon.
- Confirm `docker version` works from the same terminal.
- Check that the configured image exists with `docker image ls`.
- Pull the default image if required.
- Verify **Setup → Advanced Settings** matches the intended OpenFOAM version.

### Tutorials keep loading or show no results

- Confirm Docker integration reports ready.
- Check that the configured image contains `/opt/openfoam<version>/etc/bashrc`.
- Re-open **Import Tutorial** to trigger a cached-state republish.
- Inspect server output for tutorial-discovery errors.

### No active cases are available

- Create or import a case under **Setup**.
- Confirm `CASE_ROOT` exists and is writable.
- Select **Refresh List** after adding a case outside the application.

### A restored active case disappears

The backup stores the case name and root path, not the case directory. Copy the case data to the restored `CASE_ROOT`, or update the root path and refresh.

### A dataset does not load

- Confirm the extension appears in [Supported datasets](#supported-datasets).
- For case auto-loading, verify the file is inside the active case directory.
- Use a server-local `--data` path for very large datasets.

### The selected server port is already in use

Run the installer with another port or request automatic assignment:

```bash
./install.sh --port 8090
./install.sh --auto-port
```

For an already installed application, a one-time launch override remains
available:

```bash
./start.sh --port 8090
```

### Installation diagnostics fail

Run `python manage.py doctor` with the installed interpreter and inspect the JSON result. A missing Docker executable is a warning because the UI can start without it, but OpenFOAM tutorial and simulation operations require a reachable daemon.

## Security notes

FOAMTrame can execute Docker containers and OpenFOAM commands against local case
directories. **Run it only in a trusted environment**, review imported state files,
and keep the default loopback binding for local use. The Settings restore flow
validates structure and file size, but a restored case-root path still controls
where the application reads and writes case data.

Optional controls are under **Settings → Security**. The entire security feature
set is disabled by default and no optional policy is enforced until **Enable
optional security controls** is switched on and saved:

- **Allow network access** changes the Trame listener from `127.0.0.1` to
  `0.0.0.0`. A CLI `--host` value still takes precedence.
- **CORS** defaults to same-origin, can allow one exact trusted HTTP(S) origin, or
  can allow any origin. The any-origin mode is intentionally marked unsafe.
- **Security headers** add content-type, referrer, framing, and permissions-policy
  protections to Trame and companion-API responses.
- **API key protection** applies to mutating companion-API calls. Keys are generated
  with cryptographic randomness and persisted only as PBKDF2-SHA256 hashes. Copy a
  new key before saving because it cannot be displayed again.
- **Request and WebSocket limits** cap companion-API request bodies and wslink
  messages between 1 and 64 MiB.
- **Session timeout** is disabled by default. When enabled, FOAMTrame stops after
  the configured 1–1440 minute grace period with no browser connected. It does not
  interrupt an active browser session.

Listener, CORS, WebSocket-limit, and session-timeout changes require an application restart. The
companion API evaluates its CORS, header, request-size, and API-key policy on each
request. CORS is a browser policy—not authentication—and TLS should still terminate
at a trusted reverse proxy for any network deployment.

Do not expose the single-process application directly to an untrusted network. A hosted or multi-user deployment needs TLS at a reverse proxy, authentication, per-user authorization, resource quotas, and a Trame launcher/process-isolation strategy. Chatbot actions that create cases, execute containers, or alter files must use the confirmation and audit boundary described in [Architecture](#architecture).

## License

FOAMTrame is licensed under the [GNU General Public License v3.0](./LICENSE). See the repository's [LICENSE](./LICENSE) file for the complete terms.
