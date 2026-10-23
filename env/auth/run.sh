#!/bin/bash
# Container entrypoint: keep a copy of the log where the tests can read it.
# entrypoint.sh replaces this shell as PID 1, so its exit status is the
# container's (restart: on-failure works) and its exit tears down every
# leftover child with the PID namespace.
mkdir -p /cache/run
: > /cache/run/auth.log
chmod 644 /cache/run/auth.log
exec > >(tee -a /cache/run/auth.log) 2>&1
exec /etc/authenv/entrypoint.sh
