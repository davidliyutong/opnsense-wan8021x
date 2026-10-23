#!/bin/sh
# Point apt at a fixed snapshot.debian.org date so package versions stay identical
# across rebuilds. An empty argument keeps the default mirrors.
set -e
if [ -n "$1" ]; then
    cat > /etc/apt/sources.list.d/debian.sources <<SRC
Types: deb
URIs: http://snapshot.debian.org/archive/debian/$1
Suites: trixie trixie-updates
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://snapshot.debian.org/archive/debian-security/$1
Suites: trixie-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
SRC
fi
apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=5 update
