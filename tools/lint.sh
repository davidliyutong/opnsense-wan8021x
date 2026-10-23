#!/bin/sh
# Style and static checks that run on Linux (dev container). The upstream
# "make lint" needs FreeBSD tools and runs inside the VM (tools/vmctl.py lint).
# Usage: tools/lint.sh PLUGIN_DIR
set -u
plugin=${1:?plugin directory}
src=$plugin/src
rc=0
step() { echo ">>> $*"; }
fail() { rc=1; }

step "php -l"
find "$src" -name '*.php' -o -name '*.inc' | while read -r f; do
	php -l "$f" >/dev/null || echo "syntax error: $f"
done | grep . && fail

step "phpcs (opnsense/core ruleset)"
phpcs --standard=vendor/core/ruleset.xml --extensions=php,inc --runtime-set ignore_warnings_on_exit 1 -q "$src/etc/inc" "$src/opnsense" || fail

step "pycodestyle (as upstream: E501 ignored)"
python3 -m pycodestyle --ignore=E501 "$src" || fail

step "python syntax"
find "$src" -name '*.py' -exec python3 -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' {} + || fail

step "no direct process execution in PHP (upstream lint-exec, needs git)"
git grep --untracked -n -e '[^li][^w>:]exec(' -e '^exec(' -e 'shell_exec(' -e '[^f]passthru(' -e '^passthru(' \
	-e '[^._a-z]system(' -e '^system(' -- "$src" ':!*.js' ':!*.py'
[ $? = 1 ] || fail  # 1: no match

step "xmllint"
find "$src" -name '*.xml' -exec xmllint --noout {} + || fail

step "shellcheck"
shellcheck -s sh -e SC1091,SC2034 "$src/etc/rc.d/"* || fail
shellcheck -s sh tools/lint.sh env/auth/authctl.sh env/auth/portctl.sh env/auth/gen-certs.sh \
	env/auth/authctl-sock.sh env/vm/entrypoint.sh env/apt-snapshot.sh tools/bin/vm-ssh || fail
shellcheck -s bash env/auth/entrypoint.sh env/auth/run.sh || fail

[ $rc = 0 ] && echo ">>> all checks passed"
exit $rc
