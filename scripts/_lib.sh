# Shared helpers for the developer entry points in this directory.
# Sourced by the other scripts; not executable on its own.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT

if [ -t 1 ]; then
  _bold="$(printf '\033[1m')"
  _red="$(printf '\033[31m')"
  _reset="$(printf '\033[0m')"
else
  _bold=""
  _red=""
  _reset=""
fi

section() {
  printf '\n%s==> %s%s\n' "${_bold}" "$1" "${_reset}"
}

fail() {
  printf '%serror:%s %s\n' "${_red}" "${_reset}" "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    fail "'$1' is required but was not found on PATH. See the prerequisites in README.md."
}

require_env_file() {
  [ -f "${REPO_ROOT}/.env" ] ||
    fail ".env is missing. Create it with: cp .env.example .env"
}

require_installed_dependencies() {
  [ -d "${REPO_ROOT}/apps/api/.venv" ] && [ -d "${REPO_ROOT}/node_modules" ] ||
    fail "Dependencies are not installed. Run: ./scripts/install"
}

# Put .env into the environment of everything this script runs. Compose reads
# .env by itself; Alembic and pytest run on the host and would otherwise fall
# back to the defaults compiled into app/core/settings.py. The file is sourced,
# so a value containing a space or a semicolon has to be quoted — .env.example
# quotes the one value that needs it.
load_env() {
  require_env_file
  set -a
  # shellcheck disable=SC1091 # runtime path, nothing to check at lint time
  . "${REPO_ROOT}/.env"
  set +a
}

# Fail with an instruction rather than a page of connection errors from pytest.
# The address is whatever the application itself would resolve, so this checks
# the configuration the tests are about to use.
require_database() {
  (
    cd "${REPO_ROOT}/apps/api"
    uv run python -c '
import socket
import sys

from sqlalchemy import make_url

from app.core.settings import get_settings

url = make_url(get_settings().database_url)
try:
    socket.create_connection((url.host or "localhost", url.port or 5432), timeout=3).close()
except OSError as error:
    sys.exit(f"{url.host}:{url.port} — {error}")
'
  ) || fail "PostgreSQL is not reachable. Start it with: docker compose up -d db"
}
