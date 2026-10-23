#!/bin/sh
# Run the GitHub workflows with act, on a clean clone of HEAD, in job
# containers capped like a GitHub-hosted ubuntu-latest runner for private
# repositories (2 CPU, 8 GB RAM, no swap). Disk (14 GB there) cannot be capped
# with overlay2, see docs/testenv.md for measured usage.
# Usage: tools/ci-local.sh [act arguments, e.g. -j lint]
set -eu
root=$(pwd)
# vmactions/freebsd-vm syncs $HOME/work into the VM, as on a GitHub runner
# (/home/runner/work/REPO/REPO), so the clone lives in $home/work.
home=$root/.cache/act
ws=$home/work/repo
: "${ACT_IMAGE:?set ACT_IMAGE (env/versions.env)}"

rm -rf "$ws"
git clone -q "$root" "$ws"
git -C "$ws" checkout -q --detach "$(git rev-parse HEAD)"
git config -f .gitmodules --get-regexp '\.path$' | while read -r key path; do
	name=${key#submodule.}
	name=${name%.path}
	git -C "$ws" config "submodule.$name.url" "$root/$path"
done
git -C "$ws" -c protocol.file.allow=always submodule update -q --init

docker build -q --build-arg ACT_IMAGE="$ACT_IMAGE" -t wan8021x/act:local env/act >/dev/null
exec act -C "$ws" -P ubuntu-latest=wan8021x/act:local --pull=false \
	--env HOME="$home" --artifact-server-path "$home/artifacts" \
	--container-options "--cpus=2 --memory=8g --memory-swap=8g --device /dev/kvm" \
	push "$@"
