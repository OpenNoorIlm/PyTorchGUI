#!/usr/bin/env bash
# start.sh -- thin wrapper around start.py.  See start.py --help.
set -e
cd "$( dirname "${BASH_SOURCE[0]}" )"
if command -v python3 >/dev/null 2>&1; then
    exec python3 start.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python start.py "$@"
fi
echo "python not found in PATH" >&2
exit 1
