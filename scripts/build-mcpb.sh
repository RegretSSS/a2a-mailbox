#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TAR="/mnt/c/Users/user-a/a2a-mailbox-publish.tar"
OUT_DIR="${1:-/mnt/c/Users/user-a/mcpb-build-next}"

bash "$REPO/scripts/publish.sh" >/dev/null

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/tree" "$STAGE/pack"
tar -xf "$TAR" -C "$STAGE/tree"
for item in mcp common hub LICENSE README.md; do
  cp -r "$STAGE/tree/repo/$item" "$STAGE/pack/$item"
done
cp "$REPO/packaging/mcpb/manifest.json" "$REPO/packaging/mcpb/pyproject.toml" "$STAGE/pack/"

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/a2a-mailbox.mcpb"
python3 - "$STAGE/pack" "$OUT" <<'PY'
import sys
import zipfile
from pathlib import Path

pack, out = Path(sys.argv[1]), Path(sys.argv[2])
FIXED_MTIME = (1980, 1, 1, 0, 0, 0)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(pack.rglob("*")):
        if path.is_dir():
            continue
        info = zipfile.ZipInfo(path.relative_to(pack).as_posix(), date_time=FIXED_MTIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, path.read_bytes())
PY

VERSION="$(python3 -c 'import sys; sys.path.insert(0, "'"$REPO"'"); from common.version import __version__; print(__version__)')"
echo "mcpb ok: $OUT"
echo "version: $VERSION"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
echo "发新版时把此 sha256 更新进 server.json 的 fileSha256, identifier 的 v$VERSION 同步"
