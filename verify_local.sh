#!/usr/bin/env bash
# Set up an isolated environment and run the available project checks.
set -Eeuo pipefail
cd "$(dirname "$(realpath "$0")")"
command -v python3 >/dev/null 2>&1 || { echo 'ERROR: python3 is required.' >&2; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("ERROR: Python 3.10+ required; found " + sys.version.split()[0])
print("Python:", sys.version.split()[0])
PY
[[ -d .venv ]] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m compileall -q app.py tests
python -W error::ResourceWarning -m unittest discover -s tests -t .
echo
echo 'Checks finished. Migration tests need the original Git history; source-only ZIPs may skip them.'
echo 'Browser layout/accessibility checks are not performed by this script.'
