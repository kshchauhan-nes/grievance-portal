#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(realpath "$0")")"
if [[ -d .venv ]]; then
    source .venv/bin/activate
elif [[ -d venv ]]; then
    source venv/bin/activate
else
    echo "ERROR: No virtual environment found (.venv or venv)." >&2
    exit 1
fi

mkdir -p test-reports
REPORT="test-reports/test-$(date +%Y%m%d-%H%M%S).log"

echo "Grievance Portal — Automated Test Runner"
echo "Report: $REPORT"
echo

set +e
{
    echo "Date: $(date)"
    echo "Python: $(python --version 2>&1)"
    echo
    echo "=== Syntax check ==="
    python -m compileall -q app.py tests
    SYNTAX=$?
    echo "Syntax check exit code: $SYNTAX"
    echo
    echo "=== Unit tests ==="
    python -W error::ResourceWarning -m unittest discover -s tests -t .
    TESTS=$?
    echo
    echo "=== RESULT ==="
    if [[ $SYNTAX -eq 0 && $TESTS -eq 0 ]]; then
        echo "PASS: All executed checks succeeded."
    else
        echo "FAIL: One or more checks failed."
    fi
    echo "Syntax exit code: $SYNTAX"
    echo "Test exit code: $TESTS"
} 2>&1 | tee "$REPORT"
PIPESTATUS=( "${PIPESTATUS[@]}" )
set -e

echo
echo "Report saved to: $REPORT"
[[ ${TESTS:-1} -eq 0 && ${SYNTAX:-1} -eq 0 ]]
