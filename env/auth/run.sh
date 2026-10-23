#!/bin/sh
# Container entrypoint: keep a copy of the log where the tests can read it.
mkdir -p /cache/run
: > /cache/run/auth.log
chmod 644 /cache/run/auth.log
/etc/authenv/entrypoint.sh 2>&1 | tee -a /cache/run/auth.log
