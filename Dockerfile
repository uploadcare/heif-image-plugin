FROM ubuntu:20.04

WORKDIR /src

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked set -ex \
    && rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked set -ex \
    && apt-get install --no-install-recommends -y \
        git curl ca-certificates python3-pip build-essential make

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked set -ex \
    && apt-get install --no-install-recommends -y \
        python3-dev libpng-dev libjpeg-dev \
    && pip install --no-cache-dir -U pip

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked set -ex \
    && BUCKET=https://uploadcare-packages.s3.amazonaws.com \
    && curl -fLO $BUCKET/libheif/libheif-uc_1.16.2-6ee6762-3f6b709_$(dpkg --print-architecture).deb \
    && dpkg -i *.deb \
    && rm *.deb
