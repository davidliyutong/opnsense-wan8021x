# Job image for running .github/workflows locally with act (tools/ci-local.sh).
# catthehacker's image stands in for ubuntu-latest but lacks rsync, which
# vmactions/freebsd-vm expects on the host to sync the workspace into the VM.
ARG ACT_IMAGE
FROM ${ACT_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*
