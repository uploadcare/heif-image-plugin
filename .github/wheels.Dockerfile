ARG BASE=manylinux
FROM quay.io/pypa/manylinux_2_28:2026.10.03-1 AS manylinux-image
FROM quay.io/pypa/musllinux_1_2:2026.10.03-1 AS musllinux-image

# -------------------------------- build -----------------------------------------------
FROM ${BASE}-image AS build

ARG BASE
ENV PATH="/opt/python/cp39-cp39/bin:${PATH}"
WORKDIR /src

COPY . ./

RUN python -m pip wheel --no-deps --wheel-dir /unrepaired . \
    && case "$BASE" in \
        manylinux) platform="manylinux_2_28_$(uname -m)" ;; \
        musllinux) platform="musllinux_1_2_$(uname -m)" ;; \
    esac \
    && auditwheel repair --exclude libheif.so.1 --only-plat --plat "$platform" \
        --wheel-dir /wheels /unrepaired/*.whl \
    && python .github/scripts/check-wheel.py /wheels/*.whl "$platform"


# -------------------------------- wheel export ----------------------------------------
FROM scratch AS wheel
COPY --from=build /wheels/ /
