ARG STACK=system

# -------------------------------- base ------------------------------------------------
# Ubuntu 24.04 comes with libheif 1.17.6, which is compatible with pyheif 0.8.0
FROM ubuntu:24.04 AS base

ENV LANG=C.UTF-8
ENV PATH="/opt/venv/bin:$PATH"
ENV PIP_NO_CACHE_DIR=1

WORKDIR /src

RUN set -ex \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        git curl ca-certificates build-essential make \
        python3-dev python3-venv libffi-dev \
        libjpeg-dev libpng-dev libtiff-dev liblcms2-dev

RUN set -ex \
    && python3 -m venv /opt/venv \
    && pip install -U pip setuptools


# -------------------------------- libheif-embedded ------------------------------------
# libheif embedded in pyheif (1.18.2) + binaries from system packages (1.17.6)
FROM base AS libheif-embedded

RUN set -ex \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        libheif-dev libheif-examples \
        libheif-plugin-libde265 libheif-plugin-x265 libheif-plugin-aomenc


# -------------------------------- libheif-system ------------------------------------
# libheif and binaries from system packages (1.17.6)
FROM libheif-embedded AS libheif-system

RUN pip install --no-binary=pyheif pyheif==0.8.0


# -------------------------------- libheif-ucare ---------------------------------------
# Recent libheif and binaries from Uploadcare, patched pyheif
FROM base AS libheif-ucare

ARG LIBHEIF_UC_VERSION=1.21.2-62f1b8c-1a671c7

RUN set -ex \
    && BUCKET=https://uploadcare-packages.s3.amazonaws.com \
    && curl -fLO $BUCKET/libheif/libheif-uc_${LIBHEIF_UC_VERSION}_$(dpkg --print-architecture).deb \
    && apt-get update \
    && apt-get install --no-install-recommends -y ./*.deb \
    && rm *.deb

RUN pip install git+https://github.com/uploadcare/pyheif.git@v0.8.0-libheif-compat


# -------------------------------- development -----------------------------------------
FROM libheif-${STACK} AS development

ARG PILLOW=latest

COPY . .
RUN pip install --only-binary=pyheif --group dev-pillow-${PILLOW} -e .
