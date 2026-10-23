ARG DEBIAN_IMAGE
FROM ${DEBIAN_IMAGE}
ARG DEBIAN_SNAPSHOT
COPY env/apt-snapshot.sh /usr/local/sbin/apt-snapshot.sh
RUN sh /usr/local/sbin/apt-snapshot.sh "${DEBIAN_SNAPSHOT}" \
    && apt-get install -y --no-install-recommends \
       hostapd dnsmasq nftables iproute2 openssl tcpdump procps socat \
    && rm -rf /var/lib/apt/lists/*
COPY env/auth/ /etc/authenv/
RUN chmod +x /etc/authenv/*.sh && ln -s /etc/authenv/authctl.sh /usr/local/bin/authctl
ENTRYPOINT ["/etc/authenv/entrypoint.sh"]
