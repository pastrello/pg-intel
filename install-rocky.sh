#!/usr/bin/env bash
set -Eeuo pipefail

# PG Intelligence installer for Rocky Linux / RHEL-like systems.
# Safe defaults:
#   - does not change the monitored PostgreSQL automatically
#   - does not start a new service unless --enable is supplied
#   - keeps DB passwords out of pgintel.ini via PGPASSFILE

VERSION="0.1.2"
PREFIX="${PREFIX:-/opt/pg-intelligence}"
CONFIG_DIR="${CONFIG_DIR:-/etc/pgintel}"
STATE_DIR="${STATE_DIR:-/var/lib/pgintel}"
LOG_DIR="${LOG_DIR:-/var/log/pgintel}"
SERVICE_USER="${SERVICE_USER:-pgintel}"
SERVICE_GROUP="${SERVICE_GROUP:-pgintel}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SERVICE_NAME="pgintel.service"

INSTALL_DEPS=1
INTERACTIVE_CONFIG=0
ENABLE_SERVICE=0
FORCE_CONFIG=0
RUN_TESTS=1

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
                    pgintel.ini + /etc/pgintel/pgpass interactively.
  --enable          Run 'pgintel check' and, only if successful, enable/start
                    the systemd service.
  --force-config    Replace an existing pgintel.ini with the example/default.
                    A timestamped backup is created first.
  --no-dnf          Do not install missing OS packages with dnf.
  --skip-tests      Skip the bundled unit tests during installation.
  -h, --help        Show this help.

Environment overrides:
  PREFIX, CONFIG_DIR, STATE_DIR, LOG_DIR, SERVICE_USER, SERVICE_GROUP, PYTHON_BIN

Recommended first installation:
  sudo ./install-rocky.sh --configure

After applying the PostgreSQL SQL steps from docs/SEMI_PRODUCTION_HOWTO.md:
  sudo ./install-rocky.sh --enable
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configure) INTERACTIVE_CONFIG=1 ;;
    --enable) ENABLE_SERVICE=1 ;;
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
  case "${ID:-}" in
    rocky|rhel|almalinux|centos) ;;
    *) warn "OS '${ID:-unknown}' was not explicitly tested; continuing." ;;
  esac
fi

install_dependencies() {
  local missing=()
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || missing+=(python3)
  command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl is required."

  if (( ${#missing[@]} > 0 )); then
    (( INSTALL_DEPS == 1 )) || die "Missing packages/tools: ${missing[*]} (--no-dnf selected)."
    command -v dnf >/dev/null 2>&1 || die "dnf not found; install Python 3 manually."
    log "Installing required OS packages: ${missing[*]} python3-pip"
    dnf -y install "${missing[@]}" python3-pip
  elif ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    (( INSTALL_DEPS == 1 )) || die "python3-pip is missing (--no-dnf selected)."
    command -v dnf >/dev/null 2>&1 || die "dnf not found; install python3-pip manually."
    log "Installing python3-pip"
    dnf -y install  python3-pip
  fi

  "$PYTHON_BIN" - <<'PY' || die "Python 3.9 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
}

ensure_service_account() {
  if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
    groupadd --system "$SERVICE_GROUP"  fi
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system \
      --gid "$SERVICE_GROUP" \
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
    cp -a "$file" "${file}.bak.$(date +%Y%m%d%H M%S)"
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

  # Keep the example always current.
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

install_python() {
  if [[ ! -x "$PREFIX/venv/bin/python" ]]; then
    log "Creating Python virtual environment"
    "$PYTHON_BIN" -m venv "$PREFIX/venv" || die "Could not create venv. Verify the Python venv module is installed."
  fi

  local local_wheel=""
  if compgen -G "$PREFIX/dist/pg_intelligence-*.whl" >/dev/null; then
    local_wheel="$(ls -1 "$PREFIX"/dist/pg_intelligence-*.whl | sort -V | tail -1)"
  fi

  if [[ -n "$local_wheel" ]]; then
    log "Installing PG Intelligence from bundled wheel: $(basename "$local_wheel")"
    "$PREFIX/venv/bin/python" -m pip install --quiet --upgrade "$local_wheel" || \
      die "Python dependency installation failed. Ensure PyPI access for psycopg[binary] or preinstall it in the venv."
  else
    log "Bundled wheel not found; installing from local source tree"
    "$PREFIX/venv/bin/python" -m pip install --quiet --upgrade --no-build-isolation "$PREFIX" || \
      die "Python installation failed. Ensure setuptools and psycopg[binary] are available."
  fi

  "$PREFIX/venv/bin/python" - <<PY
import pgintel, psycopg
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
  local instance source_host source_port source_db source_user source_password
  local repo_host repo_port repo_db repo_user repo_password

  log "Interactive configuration. Passwords are stored only in $CONFIG_DIR/pgpass."
  instance="$(prompt_default 'Instance name' "$(hostname -s))"
  source_host="$(prompt_default 'Monitored PostgreSQL host' '127.0.0.1')"
  source_port="$(prompt_default 'Monitored PostgreSQL port' '5432')"
  source_db="$(prompt_default 'Monitored database' 'postgres')"
  source_user="$(prompt_default 'Monitoring role' 'pgintel')"
  read -r -s -p "Password for ${source_user} on monitored PostgreSQL (ENTER to leave unchanged/not add): " source_password; echo

  repo_host="$(prompt_default 'Repository PostgreSQL host' '127.0.0.1')"
  repo_port="$(prompt_default 'Repository PostgreSQL port' '5432')"
  repo_db="$(prompt_default 'Repository database' 'pgintel')"
  repo_user="$(prompt_default 'Repository role' 'pgintel_repo')"
  read -r -s -p "Password for ${repo_user} on repository PostgreSQL (ENTER to leave unchanged/not add): " repo_password; echo

  backup_if_needed "$CONFIG_DIR/pgintel.ini"
  cat > "$CONFIG_DIR/pgintel.ini" <<EOF_CFG
˜YÙ[Bš[œÝ[˜ÙWÛ˜[YHH	[œÝ[˜ÙBš[\˜[ÜÙXÛÛ™ÈHŒœÝÜ™WÜ]Y\žWÝ^H˜[ÙB‚–ÜÛÝ\˜ÙWB™ÛˆHÜÝIÛÝ\˜ÙWÚÜÝÜIÛÝ\˜ÙWÜÜ›˜[YOIÛÝ\˜ÙWÙˆ\Ù\IÛÝ\˜ÙWÝ\Ù\ˆÛÛ›™XÝÝ[Y[Ý]MH\XØ][Û—Û˜[YO\Ú[[XYÙ[‚–Ü™\ÜÚ]ÜžWB™ÛˆHÜÝI™\×ÚÜÝÜI™\×ÜÜ›˜[YOI™\×Ùˆ\Ù\I™\×Ý\Ù\ˆÛÛ›™XÝÝ[Y[Ý]MH\XØ][Û—Û˜[YO\Ú[[XYÙ[‚–Ø[˜[\Ú\×Bœ]Y\žWÜ™YÜ™\ÜÚ[Û—Ü˜][ÈHËŒœ]Y\žWÜ™YÜ™\ÜÚ[Û—ÛZ[—Û\ÈHLŒœ]Y\žWÜ™YÜ™\ÜÚ[Û—ÛZ[—ØØ[ÈHB™XYÝ\WÜ˜][ÈHŒŒ[\Øž]\×Ø[\HLÌÍÍN›\™ÙWÝ[\ÙYÚ[™^Øž]\ÈHLÌÍÍN‘SÑ—ÐÑ‘ÂˆÚÝÛˆ›ÛÝˆ‰ÑT•’PÑWÑÔ“ÕTˆ‰ÓÓ‘’Q×ÑT‹ÜÚ[[š[šH‚ˆÚ[Ù‰ÓÓ‘’Q×ÑT‹ÜÚ[[š[šH‚‚ˆÈ™\Ù\™HÛÛ[Y[ËÛÝ\ˆ[šY\È[™™\XÙHÛ›H^XÝÛÛ›™XÝ[ÛˆÙ^\Ë‚ˆØØ[\ˆ\H‰
ZÝ[\
H‚ˆ]ÚÈQŽˆ]ˆH‰ÛÝ\˜ÙWÚÜÝˆ]ˆH‰ÛÝ\˜ÙWÜÜˆ]ˆH‰ÛÝ\˜ÙWÙˆˆ]ˆOH‰ÛÝ\˜ÙWÝ\Ù\ˆˆˆ]ˆšH‰™\×ÚÜÝˆ]ˆœH‰™\×ÜÜˆ]ˆ™H‰™\×Ùˆˆ]ˆOH‰™\×Ý\Ù\ˆˆˆ	Ð‘QÒSžÓÑ”ÏHŽˆŸBˆ×ˆËÈ‘ˆHÜš[È™^Bˆ
	OOZ	‰ˆ	O\	‰ˆ	ÏOY	‰ˆ	O]JHÛ™^Bˆ
	OO\š	‰ˆ	O\œ	‰ˆ	ÏO\™	‰ˆ	O\JHÛ™^BˆÜš[IÈ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈˆˆ‰\‚‚ˆØ]‰\ˆˆ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ‚ˆ›HYˆ‰\‚ˆYˆÖÈ[ˆ‰ÛÝ\˜ÙWÜ\ÜÝÛÜ™ˆWNÈ[‚ˆš[ˆ	É\Î‰\Î‰\Î‰\Î‰\×‰Èˆ‰
Ü\Ü×Ù\ØØ\H‰ÛÝ\˜ÙWÚÜÝŠHˆ‰
Ü\Ü×Ù\ØØ\H‰ÛÝ\˜ÙWÜÜŠHˆˆ‰
Ü\Ü×Ù\ØØ\H‰ÛÝ\˜ÙWÙˆŠHˆ‰
Ü\Ü×Ù\ØØ\H‰ÛÝ\˜ÙWÝ\Ù\ˆŠHˆˆ‰
Ü\Ü×Ù\ØØ\H‰ÛÝ\˜ÙWÜ\ÜÝÛÜ™ŠHˆˆ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ‚ˆšBˆYˆÖÈ[ˆ‰™\×Ü\ÜÝÛÜ™ˆWNÈ[‚ˆš[ˆ	É\Î‰\Î‰\Î‰\Î‰\×‰Èˆ‰
Ü\Ü×Ù\ØØ\H‰™\×ÚÜÝŠHˆ‰
Ü\Ü×Ù\ØØ\H‰™\×ÜÜŠHˆˆ‰
Ü\Ü×Ù\ØØ\H‰™\×ÙˆŠHˆ‰
Ü\Ü×Ù\ØØ\H‰™\×Ý\Ù\ˆŠHˆˆ‰
Ü\Ü×Ù\ØØ\H‰™\×Ü\ÜÝÛÜ™ŠHˆˆ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ‚ˆšBˆÚÝÛˆ‰ÑT•’PÑWÕTÑTˆŽˆ‰ÑT•’PÑWÑÔ“ÕTˆ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ‚ˆÚ[ÙŒ‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ‚ˆÙÈÛÛ™šYÝ\˜][ÛˆÜš][‹ˆ^\Ý[™ÈÚ[[š[šHØ\È˜XÚÙY\Ú[ˆ™\Ù[ˆ‚ŸB‚œ[—Ý\ÝÊ
HÂˆ

•S—ÕTÕÈOHH
JH™]\›ˆˆÙÈ”[›š[™È[™Y[š]\ÝÈ‚ˆ‰‘Q’VÝ™[‹Øš[‹Ü]Ûˆˆ[H[š]\Ý\ØÛÝ™\ˆ\È‰‘Q’VÝ\ÝÈˆ\BŸB‚˜[Y]WØ[™Ù[˜X›J
HÂˆÙÈ”[›š[™ÈÛÛ›™XÝ]š]KØØ\Xš[]HÚXÚÈ\ÈÙ\šXÙH\Ù\ˆ‚ˆYˆH[\Ù\ˆ]H‰ÑT•’PÑWÕTÑTˆˆKH[ˆÔTÔÑ’SOH‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈˆˆ‰‘Q’VÝ™[‹Øš[‹ÜÚ[[ˆXÈ‰ÓÓ‘’Q×ÑT‹ÜÚ[[š[šHˆÚXÚÎÈ[‚ˆYHœÚ[[ÚXÚÈ˜Z[YˆÙ\šXÙHØ\È“Õ[˜X›YÜÝ\Yˆ‚ˆšBˆÞ\Ý[XÝ[˜X›HK[›ÝÈ‰ÑT•’PÑWÓSQH‚ˆÛY\BˆÞ\Ý[XÝK[›Ë\YÙ\ˆKY[Ý]\È‰ÑT•’PÑWÓSQHˆYBŸB‚•ÐT×ÐPÕU‘OLœÞ\Ý[XÝ\ËXXÝ]™HK\]ZY]‰ÑT•’PÑWÓSQHˆ‹Ù]‹Û[	‰ˆÐT×ÐPÕU‘OLHYB‚š[œÝ[Ù\[™[˜ÚY\Â™[œÝ\™WÜÙ\šXÙWØXØÛÝ[š[œÝ[Ùš[\Âš[œÝ[Ü]Û‚‚Üš]WÜÞ\Ý[YÝ[š]Š
S•TPÕU‘WÐÓÓ‘’QÈOHH
JH	‰ˆÛÛ™šYÝ\™WÚ[\˜XÝ]™[Bœ[—Ý\ÝÂ‚šYˆ

SP“WÔÑT•’PÑHOHH
JNÈ[‚ˆ˜[Y]WØ[™Ù[˜X›B™[Yˆ

ÐT×ÐPÕU‘HOHH
JNÈ[‚ˆÙÈ”Ù\šXÙHØ\È[™XYHXÝ]™NÈ˜[Y][™ÈÛÛ™šYÝ\˜][Ûˆ™Y›Ü™H™\Ý\ˆ‚ˆYˆ[\Ù\ˆ]H‰ÑT•’PÑWÕTÑTˆˆKH[ˆÔTÔÑ’SOH‰ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈˆˆ‰‘Q’VÝ™[‹Øš[‹ÜÚ[[ˆXÈ‰ÓÓ‘’Q×ÑT‹ÜÚ[[š[šHˆÚXÚÈ‹Ù]‹Û[È[‚ˆÞ\Ý[XÝ™\Ý\‰ÑT•’PÑWÓSQH‚ˆÙÈXÝ]™HÙ\šXÙH\Ü˜YY[™™\Ý\YÝXØÙ\ÜÙ[Kˆ‚ˆ[ÙBˆØ\›ˆ•˜[Y][Ûˆ˜Z[YY\ˆ\Ü˜YKˆ^\Ý[™ÈÙ\šXÙHØ\È“Õ™\Ý\YÈ[œÜXÝÛÛ™šYÝ\˜][Û‹ˆ‚ˆšB™šB‚˜Ø]SÑ—ÑÓ‘B‚”È[[YÙ[˜ÙH	Õ‘T”ÒSÓŸH[œÝ[][ÛˆÛÛ\]Y‚‚”]Î‚ˆ\XØ][Ûˆˆ	‘Q’VˆÛÛ™šYÈˆ	ÓÓ‘’Q×ÑT‹ÜÚ[[š[šH
›ÛÝ‰ÑT•’PÑWÑÔ“ÕT
Bˆ\ÜÝÛÜ™Èˆ	ÓÓ‘’Q×ÑT‹ÜÜ\ÜÈ
	ÑT•’PÑWÕTÑTŽ‰ÑT•’PÑWÑÔ“ÕTŒ
BˆÝ]Hˆ	ÕUWÑT‚ˆÙÜÈˆ›Ý\›˜[Ý]H	ÑT•’PÑWÓSQBˆÔSØÜš\Èˆ	‘Q’VÜÜ[ˆÕËUÈˆ	‘Q’VÙØÜËÔÑSRWÔ“ÑPÕSÓ—ÒÕÕË›Y‚“™^Ý\ÈYˆ\È\ÈH™]È[œÝ[][ÛŽ‚ˆKˆ\HHÜÝÜ™TÔSÔSÝ\È[ˆHÕËUË‚ˆ‹ˆ™]šY]È	ÓÓ‘’Q×ÑT‹ÜÚ[[š[šH[™	ÓÓ‘’Q×ÑT‹ÜÜ\ÜË‚ˆËˆ˜[Y]N‚ˆÝYÈ]H	ÑT•’PÑWÕTÑTˆ[ˆÔTÔÑ’SOIÓÓ‘’Q×ÑT‹ÜÜ\ÜÈˆ	‘Q’VÝ™[‹Øš[‹ÜÚ[[XÈ	ÓÓ‘’Q×ÑT‹ÜÚ[[š[šHÚXÚÂˆˆš\œÝX[X[ÛÛXÝ[ÛŽ‚ˆÝYÈ]H	ÑT•’PÑWÕTÑTˆ[ˆÔTÔÑ’SOIÓÓ‘’Q×ÑT‹ÜÜ\ÜÈˆ	‘Q’VÝ™[‹Øš[‹ÜÚ[[XÈ	ÓÓ‘’Q×ÑT‹ÜÚ[[š[šHÛÛXÝˆKˆ[˜X›HÚ[ˆ™XYN‚ˆÞ\Ý[XÝ[˜X›HK[›ÝÈ	ÑT•’PÑWÓSQB‚•H[œÝ[\ˆ[[[Û˜[HÙ\È›ÝSTˆH[Ûš]Ü™YÜÝÜ™TÔSÛ\Ý\‹‚‘SÑ—ÑÓ‘B