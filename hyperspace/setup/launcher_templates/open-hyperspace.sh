#!/bin/sh
# Hyperspace — run this file to open the console again.
#
# Starts the door and opens your browser; close this window (or press
# Ctrl-C) to stop it. This file lives in .hyperspace/, written by the
# hyperspace-setup skill; the isolated environment it execs is provisioned
# alongside it, never the system Python.
#
# Untested on Linux at authoring time (out of scope for this row) — same
# shape as the macOS .command file, no macOS-specific behavior in it.
set -eu
cd "$(dirname "$0")/.."
exec .hyperspace/env/bin/hyperspace serve --open
