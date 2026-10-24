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
archive=$(mktemp)
trap 'rm -f "$archive"' EXIT

# copy TO TAR_ARGS...: through a file, a pipe would hide a failure of the
# creating tar from set -e (no pipefail in POSIX sh)
copy() {
	to=$1
	shift
	tar -cf "$archive" "$@"
	tar -C "$to" -xf "$archive"
}

copy "$dest/plugins" -h --exclude=.git --exclude=__pycache__ Mk Templates Scripts Keywords "$plugin"
copy "$dest/core" -C vendor/core Mk Scripts ruleset.xml contrib/parallel-lint src/opnsense/mvc/app/models
