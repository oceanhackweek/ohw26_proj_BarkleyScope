#!/usr/bin/env bash
# Serve one of this folder's marimo apps in *app* mode -- no code cells, no
# editor chrome -- and print a URL that works from outside the container.
#
# Usage:
#   ./serve.sh                 # ENSO_App.py on port 2719
#   ./serve.sh Latest_Month_App.py
#   ./serve.sh ENSO_App.py 2750
#
# This is final_notebooks/serve_app.sh generalised to take an app name, and the
# two proxy rules it documents are repeated here because both are invisible
# until they bite:
#
#   * Bind to 127.0.0.1 -- not 0.0.0.0, not ::1. jupyter-server-proxy's
#     readiness probe reaches localhost over IPv4, and getaddrinfo reports ::1
#     first in this container, so a server that auto-detects its host is never
#     seen as ready and every request 500s after a 60 s timeout.
#   * Use /proxy/absolute/<port>/, which leaves the path prefix on forwarded
#     requests, and tell marimo that prefix with --base-url. The plain
#     /proxy/<port>/ route strips it and marimo 404s everything.
#
# The default port differs from serve_app.sh's 2718 so the glider app and one of
# these can run at the same time.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="${1:-ENSO_App.py}"
PORT="${2:-2719}"
APP="$HERE/$APP_NAME"

if [[ ! -f "$APP" ]]; then
    echo "No such app: $APP" >&2
    echo "Available here:" >&2
    ls "$HERE"/*_App.py 2>/dev/null | xargs -n1 basename >&2
    exit 1
fi

# The ENSO app needs the ONC token only if you switch the live toggle on; the
# archives alone will render every panel except the current-month fingerprint.
if [[ -z "${ONC_TOKEN:-}" && ! -f "$HOME/.onc_token" ]]; then
    echo "Note: no ONC token found, so the live toggle will fail." >&2
    echo "      Set one with:  read -s -p 'ONC token: ' T && printf '%s' \"\$T\" \\" >&2
    echo "                       > ~/.onc_token && chmod 600 ~/.onc_token && unset T" >&2
    echo >&2
fi

# "/user/<name>/" under the hub; "/" under a plain `jupyter lab`.
PREFIX="${JUPYTERHUB_SERVICE_PREFIX:-/}"
BASE_URL="${PREFIX}proxy/absolute/${PORT}"

echo "Serving $APP_NAME"
echo
echo "  Open:  https://<your hub host>${BASE_URL}/"
echo "         (OceanHackWeek 2026: https://hub.cryointhecloud.com${BASE_URL}/)"
echo
echo "Ctrl-C to stop. The link only works while this stays running and while"
echo "your hub server is up -- it is proxied through that server, not public."
echo

exec marimo run "$APP" \
  --headless \
  --host 127.0.0.1 \
  --port "$PORT" \
  --base-url "$BASE_URL" \
  --no-token
