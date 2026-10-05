#!/usr/bin/env bash
# Fetch the VT323 font (SIL Open Font License) from the @fontsource/vt323 npm package into
# tools/fonts/ (git-ignored). The page loads VT323 from Google Fonts at runtime; the tests block
# that request and inject this local copy instead, so layout checks match what visitors see.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts
tmp="$(mktemp -d)"
( cd "$tmp" && npm pack @fontsource/vt323 --silent >/dev/null \
  && tar xzf fontsource-vt323-*.tgz package/files/vt323-latin-400-normal.woff2 package/LICENSE )
cp "$tmp/package/files/vt323-latin-400-normal.woff2" fonts/
cp "$tmp/package/LICENSE" fonts/LICENSE-VT323-OFL.txt
rm -rf "$tmp"
echo "installed tools/fonts/vt323-latin-400-normal.woff2"
