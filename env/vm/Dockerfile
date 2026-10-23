ARG DEBIAN_IMAGE
FROM ${DEBIAN_IMAGE}
ARG DEBIAN_SNAPSHOT
COPY env/apt-snapshot.sh /usr/local/sbin/apt-snapshot.sh
RUN sh /usr/local/sbin/apt-snapshot.sh "${DEBIAN_SNAPSHOT}" \
    && apt-get install -y --no-install-recommends \
       qemu-system-x86 qemu-utils ovmf iproute2 bzip2 socat procps \
    && rm -rf /var/lib/apt/lists/*
COPY env/vm/entrypoint.sh /usr/local/sbin/vm-entrypoint
ENTRYPOINT ["/usr/local/sbin/vm-entrypoint"]
