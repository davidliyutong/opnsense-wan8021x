ARG DEBIAN_IMAGE
FROM ${DEBIAN_IMAGE}
ARG DEBIAN_SNAPSHOT
COPY env/apt-snapshot.sh /usr/local/sbin/apt-snapshot.sh
RUN sh /usr/local/sbin/apt-snapshot.sh "${DEBIAN_SNAPSHOT}" \
    && apt-get install -y --no-install-recommends \
       ca-certificates make git rsync openssh-client curl jq socat \
       php-cli php-xml php-mbstring php-tokenizer libxml2-utils shellcheck bmake \
       python3 python3-pexpect python3-pytest python3-requests python3-jinja2 python3-pycodestyle \
    && rm -rf /var/lib/apt/lists/*
# PHP_CodeSniffer as used by "make style" upstream (PSR12 based ruleset in opnsense/core)
ARG PHPCS_VERSION=3.13.5
ARG PHPCS_SHA256=9ff3ddf1fcc6c9347a57bed63da10edfc6610e4339c6bee149e92537609c7939
RUN curl -fsSL -o /usr/local/bin/phpcs \
       https://github.com/PHPCSStandards/PHP_CodeSniffer/releases/download/${PHPCS_VERSION}/phpcs.phar \
    && echo "${PHPCS_SHA256}  /usr/local/bin/phpcs" | sha256sum -c - \
    && chmod +x /usr/local/bin/phpcs

# ssh refuses to run for a uid without a passwd entry
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -o -g ${HOST_GID} dev && useradd -o -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/bash dev
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
