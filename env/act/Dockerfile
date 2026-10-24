# Job image for running .github/workflows locally with act (tools/ci-local.sh).
# catthehacker's image stands in for ubuntu-latest but lacks rsync, which
# vmactions/freebsd-vm expects on the host to sync the workspace into the VM.
ARG ACT_IMAGE
FROM ${ACT_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*
# vmactions/freebsd-vm syncs $HOME/work and ssh reads the passwd home, so the
# runner home must hold the workspace like /home/runner/work/REPO/REPO does
ARG RUNNER_HOME
RUN awk -F: -v OFS=: -v h="${RUNNER_HOME}" '$1 == "root" { $6 = h } 1' /etc/passwd > /tmp/passwd \
    && cat /tmp/passwd > /etc/passwd && rm /tmp/passwd
ENV HOME=${RUNNER_HOME}
