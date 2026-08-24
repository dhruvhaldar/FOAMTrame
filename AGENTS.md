# FOAMTrame Agent Guide

This file applies to the entire repository. It is the durable project memory for
future contributors and coding agents. Read it before making changes, then use the
linked implementation and tests as the source of truth.

If a subproject later adds a nested `AGENTS.md`, the nearest file governs that
subtree and may refine these instructions. Explicit user instructions take
precedence over this file.

## Repository overview

FOAMTrame is a Python 3.10+ desktop-oriented web application built with Trame,
Vue 2/Vuetify, VTK, Matplotlib, Flask, SQLite, and the Docker SDK. It provides one
responsive browser workspace for managing local OpenFOAM cases: setup and tutorial
import, geometry inspection, meshing, validated simulation execution, realtime
plots, and VTK post-processing.

The main execution flow is:

```text
Browser UI
  ↕ Trame/wslink
app.py and tabs/*
  ↕ validated controllers and services
backend/*
  ├─ Docker/OpenFOAM containers
  ├─ local case workspace
  ├─ server-side VTK/Matplotlib processing
  └─ foamtrame.db via app_state.py/database.py
```

Repository areas:

- `app.py` and `tabs/`: Trame composition, shared navigation, responsive UI, and
  tab-specific state/controllers.
- `backend/`: case capabilities, Docker/OpenFOAM operations, geometry, meshing,
  plotting parsers/cache, and post-processing services.
- `app_state.py`, `database.py`, and `security.py`: persisted state, SQLite
  transactions, backup normalization, and optional security policies.
- `install.py`, `runtime.py`, `run.py`, and platform wrappers: installation, port
  selection, diagnostics, launch behavior, and dated logs.
- `static/`: bundled logos, icons, and fonts; avoid runtime CDN dependencies.
- `tests/integration/` and `tests/smoke/`: behavioral regressions and full-server
  startup coverage on Windows and Linux CI.

The application is local-first and single-process. SQLite stores operational
metadata, while OpenFOAM case directories, simulation output, and large datasets
remain on disk and are referenced by path. Docker supplies the configured OpenFOAM
runtime; Docker unavailability should degrade relevant features without preventing
the UI from starting.

## Setup commands

Run commands from the repository root. Use the platform wrapper for a normal
installation because both wrappers delegate to the same validated installer.

```powershell
# Windows
.\install.ps1
.\install.ps1 --dev
.\start.ps1
```

```bash
# Linux
./install.sh
./install.sh --dev
./start.sh
```

Useful non-interactive and diagnostic commands:

```powershell
.\install.ps1 --silent --auto-port
uv run --locked python manage.py doctor --skip-docker
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
uv run --locked python scripts/codeaudit_gate.py .  # Python 3.11+
uv run --locked pytest -q
```

Do not run a full installer merely to inspect code. Installation uses `uv sync` to
create or update `.venv` from `uv.lock`, initializes the database, checks the port,
and may download large packages. Platform installers prefer an existing CPython
3.12, otherwise the platform `python_bootstrap` script verifies and extracts the
pinned archive from `vendor/python/`. A system `uv` is then preferred;
`uv_bootstrap.py` verifies and extracts the pinned archive from `vendor/uv/` when
it is absent. All bundled tooling stays under `.foamtrame-tools/`. Use
`uv run --locked` for normal development checks.

## Code style

- Keep Python compatible with 3.10 and newer. Do not introduce syntax requiring a
  newer interpreter without changing the documented minimum and CI matrix.
- Follow the existing PEP 8-oriented style: four-space indentation, descriptive
  snake_case names, and focused functions. Match surrounding formatting where no
  automated formatter is configured.
- Prefer `pathlib.Path` for filesystem work and explicit UTF-8 for text files.
- Add type hints to new service boundaries and reusable helpers. Avoid unnecessary
  `Any`, but remain compatible with Trame's dynamic state objects.
- Keep imports side-effect conscious. In particular, runtime settings and Trame
  server creation happen during module import in some entry points.
- Use structured `logging` rather than new `print` calls in application code.
  Installer/launcher console output is the intentional exception.
- Never interpolate user-controlled values into arbitrary shell strings. Use fixed
  action IDs and argument lists.
- Trame/Vuetify state keys use snake_case. Keep Python defaults and Vue expressions
  synchronized when adding reactive state.
- No separate frontend build is required; UI components are authored in Python.
- Do not add network-loaded fonts or assets when a bundled/static asset is
  appropriate.

## Product intent

FOAMTrame is a local-first Trame/Vuetify application for creating, importing,
running, plotting, and post-processing OpenFOAM cases through Docker. The UI is
designed as a responsive, glass-styled engineering workspace rather than a generic
admin dashboard. It must remain usable on constrained laptop viewports as well as
large desktop screens.

The top-level tabs are:

1. Setup
2. Geometry
3. Meshing
4. Run/Log
5. Plots
6. Post
7. Documentation (book icon, rendered from `README.md`)
8. Settings (gear icon)

`app.py` composes the tabs and owns the shared layout/CSS. Tab-specific state,
controllers, drawer content, and main content live under `tabs/`. Backend services
live under `backend/`.

## Architectural contracts

### Entry points

- `app.py`: primary Trame server.
- `flask_server.py`: optional companion HTTP API; it is not needed by the Trame UI.
- `start.ps1` / `start.sh`: supported launchers. They invoke `run.py` so complete
  child output is captured.
- `install.ps1` / `install.sh`: thin platform wrappers around `install.py`.
- `manage.py`: database initialization and machine-readable diagnostics.

Do not duplicate application behavior independently across UI buttons, future
chatbot tools, and API routes. Prefer validated application/service actions that
can be invoked by all three surfaces.

### State and database

- SQLite (`foamtrame.db`) is the operational source of truth.
- `database.py` owns the schema and transactions.
- `app_state.py` is the stable application-facing persistence API.
- Current schema/app-state version: `2`. When changing persisted structure, update
  both schema migration behavior and backup normalization; never only bump a
  constant.
- Persisted state includes case configuration, run history, plot preferences, and
  security preferences.
- JSON is an interchange/migration format only. Do not reintroduce separate
  `case_config.json`, `run_history.json`, or other operational JSON files.
- `app_state.json.example` must track the current portable backup schema.
- Legacy JSON migration must remain recoverable and must not delete the source
  files.
- Backup/restore does not include case directories, results, Docker images, or
  uploaded datasets.

Preserve transactional writes and normalize untrusted restored data before saving
it. Database and machine-local state files stay ignored by Git.

## UI and visual system

- The visual reference is the FOAMFlask glass interface, but FOAMTrame must not gain
  a runtime dependency on the separate FOAMFlask checkout.
- Primary cyan/teal gradient colors derive from the FOAMTrame logo:
  `#069ab5` and `#0c6e87`.
- Cards use a bright, translucent glass treatment with readable contrast. Avoid
  opaque generic grey panels.
- Main card headings are intentionally prominent (approximately `text-xl`/large
  `h2` weight), and descriptive subheadings use the existing cyan text treatment.
- Inputs and their text must be vertically centered.
- Buttons within the same interaction row should have consistent height and visual
  weight. Never let buttons or cards overflow their container.
- Keep the navbar compact, responsive, and evenly spaced. The active tab uses the
  animated pill slider. Hover styling must not add a blur layer over that pill.
- Preserve visible focus states, keyboard accessibility, disabled semantics, and
  sufficient color contrast.
- Use responsive layout rules instead of fixed dimensions that only match one
  screenshot. At narrow widths, stack or scroll navigation and action rows without
  clipping content.
- Avoid large unexplained empty areas inside cards. Let content determine height
  where practical, while maintaining stable positions between Setup modes.
- Selective fading is intentional on Setup: when the user engages one creation or
  import workflow, unrelated cards may de-emphasize without becoming unreadable.
- Footer content should remain balanced and include FOAMTrame copyright, GPLv3,
  Docker/Trame attribution, and the detected OpenFOAM version with the correct logo
  from `static/icons/` (the `vXX` and `vXXXX` OpenFOAM families use different
  assets).

Most global styling is embedded in `app.py`; avoid scattering conflicting CSS
unless a component truly owns it.

## Setup behavior

- The active-case card is disabled with a polished glass-disabled treatment when
  there are no cases.
- Docker readiness and tutorial availability are related asynchronous states.
  Once Docker integration becomes ready, tutorial discovery must populate
  automatically on first application start. Users must not need to press F5.
- Do not leave tutorial discovery permanently in `Loading…` or show stale
  `No data available` while Docker is ready.
- Tutorial search, tutorial selection, and new-case inputs must remain vertically
  centered and responsive.
- The create and import modes have mode-specific top headings:
  - `Create New Case` — “Initialize a blank case with standard structure (0,
    constant, system).”
  - `Import Tutorial` — “Clone an official OpenFOAM tutorial into your workspace.”
- The tutorial browser uses a search input, scrollable selection list, and adjacent
  import action. It must fit inside its glass card at every supported viewport.
- Changing between Create and Import must not move the Active Case card upward or
  otherwise cause the top layout to jump.
- Setup footer OpenFOAM version detection should use the configured container when
  Docker is available and clearly label a configured fallback when it is not.

## Run/Log behavior

Run/Log is capability-based, not a hard-coded list of commands that are assumed to
exist.

- `backend/case/capabilities.py` scans the active case and Docker image.
- Rescan whenever the active case or relevant Docker configuration changes.
- Keep unavailable actions visible but disabled, with a concise reason.
- Prefer `Allrun` when supplied by the case author.
- Do not invent a generic `Allrun`; OpenFOAM tutorials can require ordered,
  case-specific preprocessing.
- Detect solver behavior from `system/controlDict`. Support modern `foamRun` solver
  modules and legacy dedicated solver executables.
- Gate commands by their real prerequisites, including dictionaries, processor
  directories, result times, scripts, and Docker executables.
- `Allclean` requires confirmation.
- The generated safe-clean action must preview the exact generated paths and remove
  only reviewed targets inside the active case. Never broaden its deletion scope.
- UI and future chatbot calls must execute resolved fixed action IDs, not arbitrary
  shell strings.
- The Run/Log drawer is intentionally wider than other drawers because it contains
  workflow diagnostics. Keep its inner workflow scrollbar visually consistent with
  the outer sidebar scrollbar and flush with card corner radii.
- Capability summaries should be readable prose, e.g. “Detected 6 available
  action(s) · solver: **foamRun — fluid**”. Important solver labels should retain
  emphasis.
- Reset Camera belongs in the Post drawer, not Run/Log.
- Validated simulation submissions use a single FIFO worker. Users may queue jobs
  for different cases while one is active, cancel waiting jobs, and stop only the
  active container. A queued job must retain its case path, action plan, and Docker
  runtime configuration from submission time.

## Realtime plots

- Plot data should be checked eagerly when the app starts and when an active case
  is selected. Entering Plots should show a meaningful loading state and then the
  relevant cached or live data without a manual refresh button.
- A running simulation is live; a completed simulation is cached. Do not invert the
  labels or slider state.
- Poll incrementally while a simulation is active and stop unnecessary full reads
  after completion. Existing completed results should be served from cache.
- Residual discovery must recognize `log.foamRun` in the active case. Do not claim
  it is missing when the file exists.
- Matplotlib must not emit TeX/mathtext parse failures for tick labels such as
  `$\mathdefault{10^{-3}}$`.
- Scalar-field choices must populate from available timeseries data for completed
  cases.
- Default rendered plot background is glass. User-selectable backgrounds include
  glass, white/paper, black, and grey with contrasting axes, grid, labels, and
  series colors.
- Supported fonts include bundled Roboto, Helvetica Neue-style TeX Gyre Heros,
  Arial, and Times New Roman. Do not add network font dependencies.
- Logo modes include FOAMTrame, custom upload, and none.
- Legends and logos must occupy reserved empty layout regions. They must never
  cover plotted lines, markers, labels, or meaningful values.
- Maximized plots should be rendered for the larger target size rather than merely
  stretching a low-resolution preview. Other plots remain accessible in the
  maximized sidebar, whose buttons must stay within its margins.
- PNG export is publication-oriented and always uses a white paper background,
  regardless of the interactive theme.

Relevant files are `tabs/plots_tab.py` and
`backend/plots/realtime_plots.py`. Keep the non-overlap and export tests when
changing plot layout.

## Post-processing

- VTK processing/rendering stays server-side.
- Supported reader behavior and accepted extensions are documented in `README.md`.
- Reset Camera remains in the Post sidebar.
- Preserve responsive viewer controls and do not move large dataset payloads into
  SQLite or JSON backups.

## Optional security

Security features are explicitly optional and **disabled by default**.

- `security_enabled` is the master persisted switch and defaults to `false`.
- When the master switch is off, do not enforce optional CORS filtering, security
  response headers, companion-API keys, or custom HTTP/WebSocket size limits.
- The normal server default remains loopback (`127.0.0.1`). Network binding through
  Settings is effective only when optional security is enabled; an explicit CLI
  `--host` remains an operator override.
- When enabled, supported CORS modes are same-origin, one exact trusted HTTP(S)
  origin, and any origin. Clearly label any-origin as unsafe.
- API-key protection applies to mutating companion Flask API requests through the
  `X-FOAMTrame-API-Key` header.
- Generate keys cryptographically and persist only validated PBKDF2-SHA256 hashes.
  Never store or redisplay the plain-text key.
- Validate hash algorithm, iteration count, salt length, and digest length before
  verification so restored state cannot trigger excessive PBKDF2 work.
- Security, CORS, request, and WebSocket sizes remain bounded by validation.
- The optional no-client session timeout is disabled by default, remains gated by
  the master security switch, and must never interrupt a connected browser.
- Startup-time binding/CORS/WebSocket changes require restart; communicate this in
  the UI.
- CORS is not authentication. Do not document these controls as sufficient for an
  untrusted public deployment; TLS, authentication, authorization, quotas, and
  process isolation are still required.

The implementation boundary is `security.py`, with persistence in `app_state.py`
and UI in `tabs/settings_tab.py`.

## Installer, ports, and runtime logging

- Supported Python: 3.10 or newer.
- Default Trame port is `8087`.
- Before installing anything, reserve the selected loopback port for the duration
  of installation.
- With no port option, validate `8087` and stop with an actionable error if it is
  occupied.
- `--port PORT` validates and reserves the explicit port.
- `--auto-port` asks the OS for an available port and persists it.
- Persist the successful selection in `.foamtrame-port`; start scripts and runtime
  settings consume it. `FOAMTRAME_PORT` and explicit runtime CLI arguments retain
  their documented precedence.
- Windows and Linux wrappers must remain thin and behaviorally equivalent by
  delegating to `install.py`.
- Keep the bundled `uv` version, archives, official `.sha256` files, upstream
  licenses, `uv_bootstrap.py` constants, CI version, and README synchronized.
- Keep the bundled CPython version, release date, Windows/Linux archives,
  published hashes, platform bootstrap scripts, CI version, and README
  synchronized.
- Prefer compatible CPython 3.12 interpreters already available through PATH or
  the Windows Python launcher. Never modify system PATH, registry entries, or
  existing Python installations when installing the bundled fallback.
- Bundled tooling must be checksum-verified before extraction and installed only
  under the ignored `.foamtrame-tools/` directory. Unsupported platforms should
  require a system `uv` rather than selecting an incompatible binary.
- Silent installation flags are `--silent`, `--quiet`, and `-q`.
- Silent mode is truly unattended: disable child stdin and uv progress output,
  emit no success chatter, return `0` on success, and return nonzero with the log
  location on failure.
- Silent mode does not bypass port validation. Combine it with `--auto-port` when
  an automation environment cannot guarantee `8087` is free.
- Installer automation examples belong in `README.md` and must cover Windows,
  Linux, fixed/default/automatic ports, exit codes, `.foamtrame-port`, and failure
  logs.

Operational logs are grouped by the **local start date**:

```text
logs/YYYYMMDD/foamtrame.log
logs/YYYYMMDD/run.log
logs/YYYYMMDD/install.log
```

- `log_paths.py` owns the shared date-folder convention.
- `FOAMTRAME_LOG_DIR` is a base directory; the date folder is appended beneath it.
- `foamtrame.log` rotates at 5 MiB with three backups.
- `run.log` captures the full start-script session, command, timestamps, stdout,
  stderr, and exit code.
- `install.log` captures silent installer commands and output.
- Case-local simulation archives under `<case>/logs/` are separate domain data and
  remain keyed by run ID.

## Testing and verification

Primary commands from the repository root:

```powershell
uv run --locked python -m compileall -q app.py app_state.py database.py flask_server.py security.py tabs backend
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ty check
uv run --locked pytest -q
```

On Windows, the system pytest temp root may be inaccessible. In that environment,
use a unique workspace-local base temp and remove it after the run:

```powershell
$TestTemp = Join-Path (Get-Location) ('.pytest-tmp-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $TestTemp | Out-Null
uv run --locked pytest -q --basetemp $TestTemp
```

Do not treat a `PermissionError` under `%TEMP%/pytest-of-*` as an application test
failure; rerun with the explicit base temp. Clean only the exact verified temporary
directory inside the workspace.

Test expectations:

- Persistence changes: update `tests/integration/test_persistence.py`.
- Installer/port/log-path changes: update
  `tests/integration/test_installer_port.py`.
- Security changes: update `tests/integration/test_security.py`, including both
  master-disabled and enabled behavior.
- Capability changes: update `tests/integration/test_case_capabilities.py`.
- Plot parsing/layout/export changes: update
  `tests/integration/test_realtime_plots.py`.
- OpenFOAM footer version behavior: update
  `tests/integration/test_openfoam_version.py`.
- Entry-point changes must keep `tests/smoke/test_server_starts.py` passing.

For UI changes, also inspect the actual running app at a desktop viewport and at
least one constrained viewport. Confirm no clipping, overflow, layout jump, hidden
focus state, or inaccessible navigation. Do not save or overwrite the user's real
settings merely to test conditional UI.

## Change discipline

- Preserve unrelated user changes and machine-local data. The workspace may be
  dirty.
- Do not use destructive Git commands or delete case/result data.
- Resolve and validate filesystem targets before any cleanup. Generated safe-clean
  behavior must stay inside the active case; test cleanup must stay inside the
  exact test temp directory.
- Prefer `rg` / `rg --files` for discovery.
- Use `apply_patch` for targeted source edits.
- Keep documentation, schema examples, runtime behavior, and tests synchronized.
- Keep the CodeAudit CI gate clean at medium severity and above. Use inline
  `# nosec` only for reviewed false positives and include the reason.
- Do not claim a fix is complete solely because code compiles. Run proportionate
  tests and visually verify layout changes.
- If Docker is unavailable, keep the UI functional and report the limitation
  clearly; do not turn it into an application-start failure.

## Commit and pull-request guidance

- There is no repository-specific commit-title format. Use a short imperative
  summary that names the affected behavior.
- Keep commits focused; do not mix unrelated cleanup with a functional change.
- Never commit `.venv`, databases, case results, dated logs, `.foamtrame-port`, test
  temp directories, or other machine-local artifacts.
- In a handoff or pull request, summarize user-visible behavior, compatibility or
  migration impact, and the exact verification commands/results.
- Update `README.md`, `app_state.json.example`, and this file when their documented
  contracts change.
- Run relevant focused tests during development and the complete suite before
  declaring a cross-cutting change ready.
- Do not create commits, branches, pushes, or pull requests unless the user asks.

## Useful file map

```text
app.py                         Trame composition, navbar, global CSS
app_state.py                   State normalization, backup/restore, legacy migration
database.py                    SQLite schema and transactions
security.py                    Optional security validation and enforcement
runtime.py                     Environment settings, preflight, rotating logging
log_paths.py                   logs/YYYYMMDD path convention
install.py                     Cross-platform installer implementation
uv_bootstrap.py                Verified system/bundled uv resolver and extractor
vendor/uv/                     Pinned offline uv archives, checksums, and licenses
python_bootstrap.ps1/.sh       System/bundled CPython resolver and extractor
vendor/python/                 Pinned CPython archives, hashes, and embedded licenses
run.py                         Start-session capture and signal forwarding
tabs/setup_tab.py              Cases, Docker readiness, tutorial discovery/import
tabs/run_log_tab.py            Capability UI, execution, logs, history
backend/case/capabilities.py   Validated OpenFOAM case actions
backend/simulation_queue.py    Single-worker FIFO simulation scheduling
tabs/plots_tab.py              Plot state, rendering, styling, export, maximization
backend/plots/realtime_plots.py OpenFOAM field and residual parsing/cache
tabs/visualizer_tab.py         Post-processing state and VTK controls
tabs/documentation_tab.py      README-backed in-app documentation
tabs/settings_tab.py           Backup/restore and optional security UI
static/icons/                  Product/vendor/OpenFOAM version assets
tests/integration/             Focused behavior and regression tests
tests/smoke/                   Full application startup smoke test
```

When behavior and this guide disagree, verify the tests and implementation, fix the
inconsistency, and update this file in the same change.
