#!/usr/bin/env bash
# Serve Real-Time_Glider_WebApp.py in marimo's *app* mode (no code cells, no
# editor chrome) and print a URL that can be opened from a slide.
#
# Why this exists rather than "just open it in the marimo tile": the launcher
# tile runs `marimo edit`, which shows the notebook editor. For a presentation
# you want `marimo run`, and reaching a `marimo run` server from outside the
# container means going through jupyter-server-proxy.
#
# Two things about that proxy, both learned the hard way and both documented in
# the image's own /etc/jupyter/jupyter_server_config.py:
#
#   * Bind to 127.0.0.1, not 0.0.0.0 and not ::1. The proxy's readiness probe
#     reaches localhost over IPv4, and getaddrinfo reports ::1 first in this
#     container, so a server that auto-detects its host is never seen as ready
#     and every request 500s after a 60 s timeout.
#   * Use the /proxy/absolute/<port>/ route, which leaves the whole path prefix
#     on forwarded requests, and tell marimo that prefix via --base-url. The
#     plain /proxy/<port>/ route strips it, and marimo then 404s every request
#     because it is expecting the prefix it was configured with.
#
# Usage:  ./serve_app.sh [PORT]     (default 2718)
set -euo pipefail

PORT="${1:-2718}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HERE/Real-Time_Glider_WebApp.py"

# "/user/<name>/" under the hub; "/" under a plain `jupyter lab`.
PREFIX="${JUPYTERHUB_SERVICE_PREFIX:-/}"
BASE_URL="${PREFIX}proxy/absolute/${PORT}"

echo "Serving $APP"
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
