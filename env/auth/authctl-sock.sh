#!/bin/sh
# One request per connection on /cache/run/authctl.sock: a line of authctl
# arguments in, its output and a final "rc=N" line out.
read -r line
# shellcheck disable=SC2086
/etc/authenv/authctl.sh $line 2>&1
echo "rc=$?"
