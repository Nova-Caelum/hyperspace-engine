#!/bin/sh
# Hyperspace — double-click this file to open the console again.
#
# Starts the door and opens your browser; close this window (or press
# Ctrl-C) to stop it. This file lives in .hyperspace/, written by the
# hyperspace-setup skill; the isolated environment it execs is provisioned
# alongside it, never the system Python.
set -eu
cd "$(dirname "$0")/.."
exec .hyperspace/env/bin/hyperspace serve --open
