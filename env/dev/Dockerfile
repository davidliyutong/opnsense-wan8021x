ARG DEBIAN_IMAGE
FROM ${DEBIAN_IMAGE}
ARG DEBIAN_SNAPSHOT
COPY env/apt-snapshot.sh /usr/local/sbin/apt-snapshot.sh
RUN sh /usr/local/sbin/apt-snapshot.sh "${DEBIAN_SNAPSHOT}" \
    && apt-get install -y --no-install-recommends \
       ca-certificates make git rsync openssh-client curl jq socat \
       php-cli php-xml php-mbstring libxml2-utils shellcheck \
       python3 python3-pexpect python3-pytest python3-requests python3-jinja2 \
    && rm -rf /var/lib/apt/lists/*
# ssh refuses to run for a uid without a passwd entry
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -o -g ${HOST_GID} dev && useradd -o -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/bash dev
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
