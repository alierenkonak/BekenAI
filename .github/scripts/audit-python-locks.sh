#!/usr/bin/env bash
# Audits every Python lock the project ships: CI's and the production server's
# (the server venv is built from deploy/oracle/*.lock and nothing else).
set -euo pipefail

audit() {
  pip-audit --requirement "$1" --no-deps --disable-pip --progress-spinner off
}

audit requirements/ci.lock
audit deploy/oracle/requirements.lock
# pip-audit cannot infer a version from a direct wheel URL. Derive the public release
# version so the hash-pinned CPU wheel is still audited.
torch=$(mktemp)
sed -n 's|^torch @ .*torch-\([^%]*\)%2Bcpu.*|torch==\1|p' deploy/oracle/requirements.in > "$torch"
test -s "$torch"
audit "$torch"
