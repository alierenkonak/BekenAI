#!/usr/bin/env bash
# Rebuilds the fictional sample case file offered to visitors who have no documents.
# Needs a local Chrome/Chromium; set CHROME to override the binary.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
out="$root/frontend/public/ornek/ornek-ise-iade-dosyasi.pdf"

mkdir -p "$(dirname "$out")"
"$chrome" --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$out" "file://$here/ornek-ise-iade-dosyasi.html" 2>/dev/null
echo "wrote $out"
