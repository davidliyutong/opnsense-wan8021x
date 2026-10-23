#!/bin/sh
# Lay out the plugin next to the upstream build glue the way the
# opnsense/plugins repository expects it (Mk/ includes ../core/Mk), so the
# upstream "make lint" and "make package" run unmodified on a FreeBSD host.
# Same file set as tools/vmctl.py sync_tree. Used by the CI build job.
# Usage: tools/stage.sh PLUGIN_DIR DEST
set -eu
plugin=${1:?plugin directory}
dest=${2:?destination directory}
rm -rf "$dest"
mkdir -p "$dest/plugins" "$dest/core"
tar -chf - --exclude=.git --exclude=__pycache__ Mk Templates Scripts Keywords "$plugin" |
	tar -C "$dest/plugins" -xf -
tar -C vendor/core -cf - Mk Scripts ruleset.xml contrib/parallel-lint src/opnsense/mvc/app/models |
	tar -C "$dest/core" -xf -
