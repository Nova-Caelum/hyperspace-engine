#!/bin/sh
# Rebuild ui/dist/ from a fresh clone of the pinned Caelos commit.
#
# Usage: ui/build.sh [--source <path-or-url>] [--commit <sha>] [--out <dir>]
#
#   --source   Clone source: a local path (used as a local clone source, no
#              network) or a git URL. Default: the public Caelos repo.
#   --commit   Commit to pin the build to. Default: 21a60c4 (the commit this
#              shipped bundle was built from — see ui/SOURCE.md).
#   --out      Output directory to replace wholesale with the fresh build.
#              Default: ui/dist (relative to this script's repo root).
#
# No Caelos source is ever modified by this script. A native-build failure
# (@tailwindcss/oxide, esbuild) is an *environment* problem to fix (e.g.
# `npm rebuild`) — never a reason to patch Caelos source.
set -eu

SOURCE="https://github.com/Nova-Caelum/Caelos.git"
COMMIT="21a60c4"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$SCRIPT_DIR/dist"

while [ $# -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --commit)
      COMMIT="$2"
      shift 2
      ;;
    --out)
      OUT="$2"
      shift 2
      ;;
    *)
      echo "ui/build.sh: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

TMP_BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/caelos-ui-build.XXXXXX")
cleanup() {
  rm -rf "$TMP_BUILD_DIR"
}
trap cleanup EXIT INT TERM

echo "ui/build.sh: cloning $SOURCE (no-checkout) into $TMP_BUILD_DIR" >&2
git clone --no-checkout "$SOURCE" "$TMP_BUILD_DIR"

(
  cd "$TMP_BUILD_DIR"
  echo "ui/build.sh: checking out $COMMIT" >&2
  git checkout "$COMMIT"

  echo "ui/build.sh: npm ci" >&2
  npm ci

  echo "ui/build.sh: VITE_API_BASE_URL=. npm run build" >&2
  VITE_API_BASE_URL=. npm run build
)

if [ ! -d "$TMP_BUILD_DIR/dist" ]; then
  echo "ui/build.sh: build did not produce a dist/ directory" >&2
  exit 1
fi

echo "ui/build.sh: replacing $OUT with the fresh build" >&2
rm -rf "$OUT"
mkdir -p "$(dirname -- "$OUT")"
cp -R "$TMP_BUILD_DIR/dist" "$OUT"

echo "ui/build.sh: done. Output at $OUT" >&2
