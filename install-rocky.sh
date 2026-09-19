#!/usr/bin/env bash
set -Eeuo pipefail

# PG Intelligence installer for Rocky Linux / RHEL-like systems.
# Supported installer targets: RHEL-compatible 8, 9 and 10.
# Safe defaults:
#   - only creates PG Intelligence roles/grants/repository objects during accepted bootstrap
#   - never changes shared_preload_libraries or restarts PostgreSQL
#   - does not start a new service unless --enable is supplied
#   - keeps service/admin passwords out of pgintel.ini and command-line arguments

VERSION="0.1.6"
PREFIX="${PREFIX:-/opt/pg-intelligence}"
CONFIG_DIR="${CONFIG_DIR:-/etc/pgintel}"
STATE_DIR="${STATE_DIR:-/var/lib/pgintel}"
LOG_DIR="${LOG_DIR:-/var/log/pgintel}"
SERVICE_USER="${SERVICE_USER:-pgintel}"
SERVICE_GROUP="${SERVICE_GROUP:-pgintel}"
PYTHON_BIN="${PYTHON_BIN:-}"
SERVICE_NAME="pgintel.service"

INSTALL_DEPS=1
INTERACTIVE_CONFIG=0
ENABLE_SERVICE=0
FORCE_CONFIG=0
RUN_TESTS=1
ASSESS_CAPABILITIES=0
MIGRATE_REPOSITORY=0
BOOTSTRAP_POSTGRES=0

OS_ID="unknown"
OS_MAJOR=""
CONFIG_SOURCE_PASSWORD=""
CONFIG_REPO_PASSWORD=""

log() { printf '[pgintel-installer] %s\n' "$*"; }
warn() { printf '[pgintel-installer] WARNING: %s\n' "$*" >&2; }
die() { printf '[pgintel-installer] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
PG Intelligence ${VERSION} - Rocky Linux installer

Usage:
  sudo ./install-rocky.sh [options]

Options:
  --configure       Ask for source/repository connection settings and write
                    pgintel.ini + /etc/pgintel/pgpass interactively. At the
                    end, offer an idempotent PostgreSQL bootstrap.
  --bootstrap-postgres
                    Create missing PG Intelligence roles/repository database/schema
                    and apply repository migrations. Existing unrelated objects are
                    not overwritten. pg_stat_statements remains a manual step.
  --enable          Run 'pgintel check' and, only if successful, enable/start
                    the systemd service.
  --assess          Detect PostgreSQL version/capabilities and print missing
                    monitoring versus the PostgreSQL 18 baseline.
  --migrate-repository
                    Apply idempotent PG Intelligence repository migrations only.
                    Never alters the monitored source DB.
  --force-config    Replace an existing pgintel.ini with the example/default.
                    A timestamped backup is created first.
  --no-dnf          Do not install missing OS packages with dnf.
  --skip-tests      Skip the bundled unit tests during installation.
  -h, --help        Show this help.

Environment overrides:
  PREFIX, CONFIG_DIR, STATE_DIR, LOG_DIR, SERVICE_USER, SERVICE_GROUP, PYTHON_BIN

Recommended first installation:
  sudo ./install-rocky.sh --configure

Supported installer targets: RHEL-compatible 8, 9 and 10.
CentOS 7 is legacy/best-effort. Ubuntu/Debian are out of scope for now.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configure) INTERACTIVE_CONFIG=1 ;;
    --bootstrap-postgres) BOOTSTRAP_POSTGRES=1 ;;
    --enable) ENABLE_SERVICE=1 ;;
    --assess) ASSESS_CAPABILITIES=1 ;;
    --migrate-repository) MIGRATE_REPOSITORY=1 ;;
    --force-config) FORCE_CONFIG=1 ;;
    --no-dnf) INSTALL_DEPS=0 ;;
    --skip-tests) RUN_TESTS=0 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

[[ ${EUID} -eq 0 ]] || die "Run as root (sudo)."
[[ -f pyproject.toml && -d pgintel && -d sql ]] || die "Run the installer from the project root."

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_MAJOR="${VERSION_ID%%.*}"
  case "$OS_ID" in
    rocky|rhel|almalinux|centos) ;;
    *) warn "OS '$OS_ID' is not an installer target; continuing best-effort." ;;
  esac
  if [[ "$OS_ID" =~ ^(rocky|rhel|almalinux|centos)$ && ! "$OS_MAJOR" =~ ^(8|9|10)$ ]]; then
    warn "RHEL-family major '$OS_MAJOR' is outside the supported 8/9/10 installer matrix."
  fi
fi

python_is_usable() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || return 1
  "$bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

select_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    python_is_usable "$PYTHON_BIN" || die "PYTHON_BIN=$PYTHON_BIN is missing or older than Python 3.9."
    return
  fi
  local candidate
  for candidate in python3 python3.12 python3.11 python3.10 python3.9; do
    if python_is_usable "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done
  (( INSTALL_DEPS == 1 )) || die "Python 3.9+ is required (--no-dnf selected)."
  command -v dnf >/dev/null 2>&1 || die "dnf not found; install Python 3.9+ manually."
  if [[ "$OS_MAJOR" == "8" ]]; then
    log "Installing Python 3.12 runtime for RHEL-family 8"
    dnf -y install python3.12 python3.12-pip python3.12-pip-wheel
  else
    log "Installing Python 3 runtime"
    dnf -y install python3 python3-pip
  fi
  for candidate in python3 python3.12 python3.11 python3.10 python3.9; do
    if python_is_usable "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done
  die "Could not locate a usable Python 3.9+ runtime after package installation."
}

install_dependencies() {
  command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl is required."
  select_python
  log "OS detected: ${OS_ID} ${OS_MAJOR:-unknown}; runtime selected: $($PYTHON_BIN --version 2>&1)"
  if ! "$PYTHON_BIN" -c 'import ssl, xml.parsers.expat' >/dev/null 2>&1; then
    if (( INSTALL_DEPS == 1 )) && [[ "$OS_MAJOR" == "8" && "$(basename "$(command -v "$PYTHON_BIN")")" == "python3.12" ]]; then
      log "Repairing Python 3.12 runtime dependencies (expat/python3.12-libs)"
      dnf -y upgrade expat python3.12 python3.12-libs
    fi
  fi
  "$PYTHON_BIN" -c 'import ssl, xml.parsers.expat' >/dev/null 2>&1 || die "Python runtime is inconsistent (ssl/pyexpat import failed). Update distro Python/expat packages first."
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    (( INSTALL_DEPS == 1 )) || die "pip is missing for $PYTHON_BIN (--no-dnf selected)."
    if [[ "$(basename "$(command -v "$PYTHON_BIN")")" == "python3.12" && "$OS_MAJOR" == "8" ]]; then
      log "Installing Python 3.12 pip bootstrap packages"
      dnf -y install python3.12-pip python3.12-pip-wheel
    else
      log "Installing python3-pip"
      dnf -y install python3-pip
    fi
  fi
  "$PYTHON_BIN" -m pip --version >/dev/null 2>&1 || die "pip is not functional for $PYTHON_BIN."
}

ensure_service_account() {
  if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    groupadd --system "$SERVICE_GROUP"
  fi
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system \
      --gid "$SERVICE_GROUP" \
      --home-dir "$STATE_DIR" \
      --create-home \
      --shell /sbin/nologin \
      --comment "PG Intelligence Agent" \
      "$SERVICE_USER"
  fi
}

backup_if_needed() {
  local file="$1"
  if [[ -e "$file" ]]; then
    cp -a "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
  fi
}

install_files() {
  install -d -m 0755 -o root -g root "$PREFIX"
  install -d -m 0750 -o root -g "$SERVICE_GROUP" "$CONFIG_DIR"
  install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$STATE_DIR" "$LOG_DIR"

  rm -rf "$PREFIX/pgintel" "$PREFIX/sql" "$PREFIX/tests" "$PREFIX/docs" "$PREFIX/dist"
  cp -a pgintel sql tests docs "$PREFIX/"
  if [[ -d dist ]]; then
    cp -a dist "$PREFIX/"
  else
    install -d -m 0755 -o root -g root "$PREFIX/dist"
  fi
  install -m 0644 pyproject.toml README.md CHANGELOG.md config.example.ini "$PREFIX/"

  install -m 0640 -o root -g "$SERVICE_GROUP" config.example.ini "$CONFIG_DIR/pgintel.ini.example"

  if [[ ! -f "$CONFIG_DIR/pgintel.ini" ]]; then
    install -m 0640 -o root -g "$SERVICE_GROUP" config.example.ini "$CONFIG_DIR/pgintel.ini"
    log "Created $CONFIG_DIR/pgintel.ini"
  elif (( FORCE_CONFIG == 1 )); then
    backup_if_needed "$CONFIG_DIR/pgintel.ini"
    install -m 0640 -o root -g "$SERVICE_GROUP" config.example.ini "$CONFIG_DIR/pgintel.ini"
    log "Replaced pgintel.ini (--force-config); backup retained."
  else
    chown root:"$SERVICE_GROUP" "$CONFIG_DIR/pgintel.ini"
    chmod 0640 "$CONFIG_DIR/pgintel.ini"
    log "Preserved existing $CONFIG_DIR/pgintel.ini"
  fi

  if [[ ! -f "$CONFIG_DIR/pgpass" ]]; then
    cat > "$CONFIG_DIR/pgpass" <<'PGPASS'
# PostgreSQL password file used by pgintel.service (PGPASSFILE).
# Format: hostname:port:database:username:password
# Keep this file mode 0600 and owned by the pgintel OS user.
PGPASS
  fi
  chown "$SERVICE_USER":"$SERVICE_GROUP" "$CONFIG_DIR/pgpass"
  chmod 0600 "$CONFIG_DIR/pgpass"
}

create_venv() {
  rm -rf "$PREFIX/venv"
  log "Creating Python virtual environment with $PYTHON_BIN"
  if "$PYTHON_BIN" -m venv "$PREFIX/venv"; then
    return 0
  fi
  warn "Standard venv bootstrap failed; retrying without ensurepip."
  rm -rf "$PREFIX/venv"
  "$PYTHON_BIN" -m venv --without-pip "$PREFIX/venv" || return 1
  "$PYTHON_BIN" -m pip --python "$PREFIX/venv" install --quiet pip || return 1
}

install_python() {
  if [[ ! -x "$PREFIX/venv/bin/python" ]] || ! "$PREFIX/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    create_venv || die "Could not create a functional venv with pip. Verify distro Python/venv/pip packages."
  fi
  local local_wheel=""
  if compgen -G "$PREFIX/dist/pg_intelligence-${VERSION}-*.whl" >/dev/null; then
    local_wheel="$(ls -1 "$PREFIX"/dist/pg_intelligence-${VERSION}-*.whl | sort -V | tail -1)"
  elif compgen -G "$PREFIX/dist/pg_intelligence-*.whl" >/dev/null; then
    warn "Bundled wheel does not match installer version ${VERSION}; ignoring stale wheel(s)."
  fi
  if [[ -n "$local_wheel" ]]; then
    log "Installing PG Intelligence from bundled wheel: $(basename "$local_wheel")"
    "$PREFIX/venv/bin/python" -m pip install --quiet --upgrade "$local_wheel" || die "Python dependency installation failed. Ensure PyPI access for psycopg[binary] or preinstall it in the venv."
  else
    log "Installing PG Intelligence ${VERSION} from local source tree"
    "$PREFIX/venv/bin/python" -m pip install --quiet --upgrade --no-build-isolation "$PREFIX" || die "Python installation failed. Ensure setuptools and psycopg[binary] are available."
  fi
  local installed_version
  installed_version="$("$PREFIX/venv/bin/python" -c 'import pgintel; print(pgintel.__version__)')"
  [[ "$installed_version" == "$VERSION" ]] || die "Installed PG Intelligence version $installed_version does not match installer $VERSION."
  "$PREFIX/venv/bin/python" - <<'PY'
import pgintel, psycopg, xml.parsers.expat
print(f"PG Intelligence {pgintel.__version__}; psycopg {psycopg.__version__}")
PY
}

write_systemd_unit() {
  cat > "/etc/systemd/system/$SERVICE_NAME" <<EOF_UNIT
[Unit]
Description=PG Intelligence Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$STATE_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PGPASSFILE=$CONFIG_DIR/pgpass
ExecStart=$PREFIX/venv/bin/pgintel -c $CONFIG_DIR/pgintel.ini run
Restart=on-failure
RestartSec=10
UMask=0027

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths=$STATE_DIR $LOG_DIR

[Install]
WantedBy=multi-user.target
EOF_UNIT
  chmod 0644 "/etc/systemd/system/$SERVICE_NAME"
  systemctl daemon-reload
}

pgpass_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//:/\\:}"
  printf '%s' "$s"
}

prompt_default() {
  local prompt="$1" default="$2" value
  read -r -p "$prompt [$default]: " value
  printf '%s' "${value:-$default}"
}

configure_interactively() {
  local instance source_host source_port source_db source_user source_password source_expected_major
  local repo_host repo_port repo_db repo_user repo_password

  log "Interactive configuration. Passwords are stored only in $CONFIG_DIR/pgpass."
  instance="$(prompt_default 'Instance name' "$(hostname -s)")"
  source_host="$(prompt_default 'Monitored PostgreSQL host' '127.0.0.1')"
  source_port="$(prompt_default 'Monitored PostgreSQL port' '5432')"
  source_db="$(prompt_default 'Monitored database' 'postgres')"
  source_user="$(prompt_default 'Monitoring role' 'pgintel')"
  source_expected_major="$(prompt_default 'Expected PostgreSQL major (auto or 13-18)' 'auto')"
  if [[ "$source_expected_major" != "auto" && ! "$source_expected_major" =~ ^(13|14|15|16|17|18)$ ]]; then
    die "Expected major must be auto or an integer from 13 through 18."
  fi
  read -r -s -p "Password for ${source_user} on monitored PostgreSQL (ENTER to leave unchanged/not add): " source_password; echo

  repo_host="$(prompt_default 'Repository PostgreSQL host' '127.0.0.1')"
  repo_port="$(prompt_default 'Repository PostgreSQL port' '5432')"
  repo_db="$(prompt_default 'Repository database' 'pgintel')"
  repo_user="$(prompt_default 'Repository role' 'pgintel_repo')"
  read -r -s -p "Password for ${repo_user} on repository PostgreSQL (ENTER to leave unchanged/not add): " repo_password; echo

  backup_if_needed "$CONFIG_DIR/pgintel.ini"
  cat > "$CONFIG_DIR/pgintel.ini" <<EOF_CFG
[agent]
instance_name = $instance
interval_seconds = 60
store_query_text = false

[collection]
slow_interval_seconds = 900
size_interval_seconds = 3600
max_source_cycle_seconds = 20
query_text_mode = none

[source]
dsn = host=$source_host port=$source_port dbname=$source_db user=$source_user connect_timeout=5 application_name=pgintel-agent
$( [[ "$source_expected_major" != "auto" ]] && printf 'expected_major = %s\n' "$source_expected_major" )
[repository]
dsn = host=$repo_host port=$repo_port dbname=$repo_db user=$repo_user connect_timeout=5 application_name=pgintel-agent

[analysis]
query_regression_ratio = 3.0
query_regression_min_ms = 50.0
query_regression_min_calls = 5
dead_tuple_ratio = 0.20
temp_bytes_alert = 1073741824
large_unused_index_bytes = 1073741824
EOF_CFG
  chown root:"$SERVICE_GROUP" "$CONFIG_DIR/pgintel.ini"
  chmod 0640 "$CONFIG_DIR/pgintel.ini"

  local tmp replace_source=0 replace_repo=0
  [[ -n "$source_password" ]] && replace_source=1
  [[ -n "$repo_password" ]] && replace_repo=1
  tmp="$(mktemp)"
  awk -F: -v h="$source_host" -v p="$source_port" -v d="$source_db" -v u="$source_user" \
    -v rh="$repo_host" -v rp="$repo_port" -v rd="$repo_db" -v ru="$repo_user" \
    -v replace_source="$replace_source" -v replace_repo="$replace_repo" \
    'BEGIN{OFS=":"}
     /^#/ || NF < 5 {print; next}
     (replace_source == 1 && $1==h && $2==p && $3==d && $4==u) {next}
     (replace_repo == 1 && $1==rh && $2==rp && $3==rd && $4==ru) {next}
     {print}' "$CONFIG_DIR/pgpass" > "$tmp"

  cat "$tmp" > "$CONFIG_DIR/pgpass"
  rm -f "$tmp"
  if [[ -n "$source_password" ]]; then
    printf '%s:%s:%s:%s:%s\n' \
      "$(pgpass_escape "$source_host")" "$(pgpass_escape "$source_port")" \
      "$(pgpass_escape "$source_db")" "$(pgpass_escape "$source_user")" \
      "$(pgpass_escape "$source_password")" >> "$CONFIG_DIR/pgpass"
  fi
  if [[ -n "$repo_password" ]]; then
    printf '%s:%s:%s:%s:%s\n' \
      "$(pgpass_escape "$repo_host")" "$(pgpass_escape "$repo_port")" \
      "$(pgpass_escape "$repo_db")" "$(pgpass_escape "$repo_user")" \
      "$(pgpass_escape "$repo_password")" >> "$CONFIG_DIR/pgpass"
  fi
  chown "$SERVICE_USER":"$SERVICE_GROUP" "$CONFIG_DIR/pgpass"
  chmod 0600 "$CONFIG_DIR/pgpass"
  CONFIG_SOURCE_PASSWORD="$source_password"
  CONFIG_REPO_PASSWORD="$repo_password"
  log "Configuration written. Existing pgintel.ini was backed up when present."
}

prompt_yes_no() {
  local prompt="$1" default="${2:-y}" answer suffix
  [[ "$default" == "y" ]] && suffix="Y/n" || suffix="y/N"
  read -r -p "$prompt [$suffix]: " answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy]$ ]]
}

bootstrap_interactively() {
  local source_role_password="${1:-}" repo_role_password="${2:-}"
  local source_admin_user source_admin_password repo_admin_user repo_admin_password
  log "PostgreSQL bootstrap changes only PG Intelligence roles, grants, repository DB/schema and migrations."
  log "It will NOT change shared_preload_libraries, create pg_stat_statements, or restart PostgreSQL."
  if [[ -z "$source_role_password" ]]; then
    read -r -s -p "Password to use if monitoring role must be created (ENTER if it already exists): " source_role_password; echo
  fi
  if [[ -z "$repo_role_password" ]]; then
    read -r -s -p "Password to use if repository role must be created (ENTER if it already exists): " repo_role_password; echo
  fi
  source_admin_user="$(prompt_default 'Source PostgreSQL administrator' 'postgres')"
  read -r -s -p "Password for source administrator ${source_admin_user} (ENTER for passwordless auth): " source_admin_password; echo
  repo_admin_user="$(prompt_default 'Repository PostgreSQL administrator' "$source_admin_user")"
  read -r -s -p "Password for repository administrator ${repo_admin_user} (ENTER = reuse source admin password): " repo_admin_password; echo
  [[ -n "$repo_admin_password" ]] || repo_admin_password="$source_admin_password"
  env \
    PGINTEL_SOURCE_ADMIN_PASSWORD="$source_admin_password" \
    PGINTEL_REPOSITORY_ADMIN_PASSWORD="$repo_admin_password" \
    PGINTEL_SOURCE_ROLE_PASSWORD="$source_role_password" \
    PGINTEL_REPOSITORY_ROLE_PASSWORD="$repo_role_password" \
    "$PREFIX/venv/bin/python" -m pgintel.bootstrap \
      -c "$CONFIG_DIR/pgintel.ini" \
      --sql-dir "$PREFIX/sql" \
      --source-admin-user "$source_admin_user" \
      --repository-admin-user "$repo_admin_user" || \
      die "PostgreSQL bootstrap failed. Unrelated database objects were not intentionally modified."
}

run_tests() {
  (( RUN_TESTS == 1 )) || return 0
  log "Running bundled unit tests"
  "$PREFIX/venv/bin/python" -m unittest discover -s "$PREFIX/tests" -q
}

migrate_repository_schema() {
  log "Applying PG Intelligence repository migrations"
  runuser -u "$SERVICE_USER" -- env PGPASSFILE="$CONFIG_DIR/pgpass" \
    "$PREFIX/venv/bin/pgintel" -c "$CONFIG_DIR/pgintel.ini" migrate-repository
}

assess_capabilities() {
  log "Assessing PostgreSQL version and monitoring capabilities"
  if runuser -u "$SERVICE_USER" -- env PGPASSFILE="$CONFIG_DIR/pgpass" \
      "$PREFIX/venv/bin/pgintel" -c "$CONFIG_DIR/pgintel.ini" capabilities; then
    return 0
  fi
  warn "Capability assessment could not connect yet. Apply the SQL/authentication steps, then run: sudo ./install-rocky.sh --assess"
  return 1
}

validate_and_enable() {
  log "Running connectivity/capability check as service user"
  if ! runuser -u "$SERVICE_USER" -- env PGPASSFILE="$CONFIG_DIR/pgpass" \
      "$PREFIX/venv/bin/pgintel" -c "$CONFIG_DIR/pgintel.ini" check; then
    die "pgintel check failed. Service was NOT enabled/started."
  fi
  assess_capabilities || true
  systemctl enable --now "$SERVICE_NAME"
  sleep 1
  systemctl --no-pager --full status "$SERVICE_NAME" || true
}

WAS_ACTIVE=0
systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null && WAS_ACTIVE=1 || true

install_dependencies
ensure_service_account
install_files
install_python
write_systemd_unit
if (( INTERACTIVE_CONFIG == 1 )); then
  configure_interactively
  if (( BOOTSTRAP_POSTGRES == 1 )) || prompt_yes_no "Bootstrap PG Intelligence roles/repository now?" "y"; then
    bootstrap_interactively "$CONFIG_SOURCE_PASSWORD" "$CONFIG_REPO_PASSWORD"
  fi
elif (( BOOTSTRAP_POSTGRES == 1 )); then
  bootstrap_interactively
fi
run_tests

if (( MIGRATE_REPOSITORY == 1 )); then
  migrate_repository_schema
fi

if (( ASSESS_CAPABILITIES == 1 || INTERACTIVE_CONFIG == 1 || BOOTSTRAP_POSTGRES == 1 )); then
  assess_capabilities || true
fi

if (( ENABLE_SERVICE == 1 )); then
  validate_and_enable
elif (( WAS_ACTIVE == 1 )); then
  log "Service was already active; validating configuration before restart."
  if runuser -u "$SERVICE_USER" -- env PGPASSFILE="$CONFIG_DIR/pgpass" \
      "$PREFIX/venv/bin/pgintel" -c "$CONFIG_DIR/pgintel.ini" check >/dev/null; then
    systemctl restart "$SERVICE_NAME"
    log "Active service upgraded and restarted successfully."
  else
    warn "Validation failed after upgrade. Existing service was NOT restarted; inspect configuration."
  fi
fi

cat <<EOF_DONE

PG Intelligence ${VERSION} installation completed.

Paths:
  Application : $PREFIX
  Config      : $CONFIG_DIR/pgintel.ini       (root:$SERVICE_GROUP 0640)
  Passwords   : $CONFIG_DIR/pgpass            ($SERVICE_USER:$SERVICE_GROUP 0600)
  State       : $STATE_DIR
  Logs        : journalctl -u $SERVICE_NAME
  SQL scripts : $PREFIX/sql
  HOW-TO      : $PREFIX/docs/SEMI_PRODUCTION_HOWTO.md

New installations can use --configure to bootstrap the monitoring role,
repository role/database/schema and repository migrations.

Manual PostgreSQL step intentionally retained:
  1. Add pg_stat_statements to shared_preload_libraries if needed.
  2. Restart PostgreSQL in an approved maintenance window if preload changed.
  3. In the monitored database:
       CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

Then:
  4. Assess PostgreSQL version/capabilities:
       sudo -u $SERVICE_USER env PGPASSFILE=$CONFIG_DIR/pgpass \
         $PREFIX/venv/bin/pgintel -c $CONFIG_DIR/pgintel.ini capabilities
  5. Validate:
       sudo -u $SERVICE_USER env PGPASSFILE=$CONFIG_DIR/pgpass \
         $PREFIX/venv/bin/pgintel -c $CONFIG_DIR/pgintel.ini check
  6. First production-safe manual collection (FAST only):
       sudo -u $SERVICE_USER env PGPASSFILE=$CONFIG_DIR/pgpass \
         $PREFIX/venv/bin/pgintel -c $CONFIG_DIR/pgintel.ini collect
  7. Optional one-off full inventory (includes relation sizes):
       sudo -u $SERVICE_USER env PGPASSFILE=$CONFIG_DIR/pgpass \
         $PREFIX/venv/bin/pgintel -c $CONFIG_DIR/pgintel.ini collect --full
  8. Enable when ready:
       systemctl enable --now $SERVICE_NAME

The bootstrap never changes application tables, shared_preload_libraries, or PostgreSQL service state.
EOF_DONE
