# Pinned toolchain + sandbox image for the COBOL->X verifier.
#
# This one image serves two roles:
#   1. the reference-semantics toolchain (GnuCOBOL), the checkers (JBMC, OpenJML,
#      CrossHair) and the target-language compilers;
#   2. the sandbox in which untrusted generated code is built and run
#      (the verifier always starts it with --network none, CPU/memory/pids limits,
#      a read-only source mount and a tmpfs working directory; see
#      verifier/sandbox/docker_runner.py).
#
# Every download is pinned by version AND sha256. `make image` builds it;
# /opt/toolchain/versions.sh prints the exact versions, which go into every report.

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

ARG GNUCOBOL_VERSION=3.2
ARG GNUCOBOL_SHA256=3bb48af46ced4779facf41fdc2ee60e4ccb86eaa99d010b36685315df39c2ee2
ARG CBMC_VERSION=6.8.0
ARG CBMC_SHA256=5c38bc8da449566b6ad1c8275b2f8119b86dfb7a965cb8a0505a0b4688647eb0
ARG OPENJML_VERSION=21.0.28
ARG OPENJML_SHA256=0a151820c4e680e32cb2e399a02615182c748fc24e308865b317783d4836df8a
ARG GO_VERSION=1.22.12
ARG GO_SHA256=4fa4f869b0f7fc6bb1eb2660e74657fbf04cdd290b5aef905585c86051b34d43

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=UTC

# --- base packages: build tools, JDK 17, Python, libfaketime, z3 ----------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils unzip build-essential pkg-config \
        libgmp-dev libncurses-dev \
        openjdk-17-jdk-headless maven \
        python3 python3-venv python3-dev \
        faketime libfaketime \
        z3 \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH=${JAVA_HOME}/bin:${PATH}

# --- GnuCOBOL 3.2 (reference semantics), built from the GNU release tarball ----
RUN curl -fsSL -o /tmp/gnucobol.tar.xz \
        https://ftp.gnu.org/gnu/gnucobol/gnucobol-${GNUCOBOL_VERSION}.tar.xz \
    && echo "${GNUCOBOL_SHA256}  /tmp/gnucobol.tar.xz" | sha256sum -c - \
    && mkdir /tmp/gc && tar -xJf /tmp/gnucobol.tar.xz -C /tmp/gc --strip-components=1 \
    && cd /tmp/gc \
    && ./configure --prefix=/usr/local --without-db --without-xml2 --without-json \
    && make -j"$(nproc)" && make install && ldconfig \
    && cd / && rm -rf /tmp/gc /tmp/gnucobol.tar.xz

# --- CBMC / JBMC ----------------------------------------------------------------
RUN curl -fsSL -o /tmp/cbmc.deb \
        https://github.com/diffblue/cbmc/releases/download/cbmc-${CBMC_VERSION}/ubuntu-24.04-cbmc-${CBMC_VERSION}-Linux.deb \
    && echo "${CBMC_SHA256}  /tmp/cbmc.deb" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/cbmc.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/cbmc.deb

# --- OpenJML (bundles its own JDK 21; checks Java 17 sources) -------------------
RUN curl -fsSL -o /tmp/openjml.zip \
        https://github.com/OpenJML/OpenJML/releases/download/${OPENJML_VERSION}/openjml-ubuntu-24.04-${OPENJML_VERSION}.zip \
    && echo "${OPENJML_SHA256}  /tmp/openjml.zip" | sha256sum -c - \
    && mkdir -p /opt/openjml && unzip -q /tmp/openjml.zip -d /opt/openjml && rm /tmp/openjml.zip \
    && chmod -R a+rX /opt/openjml && chmod a+x /opt/openjml/openjml*
# The stock launcher misdetects WSL inside containers on WSL2 kernels (spike S3, DECISIONS D11).
COPY openjml-linux /usr/local/bin/openjml-linux
RUN chmod a+rx /usr/local/bin/openjml-linux && ln -s /usr/local/bin/openjml-linux /usr/local/bin/openjml

# --- Go -------------------------------------------------------------------------
RUN curl -fsSL -o /tmp/go.tgz https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz \
    && echo "${GO_SHA256}  /tmp/go.tgz" | sha256sum -c - \
    && tar -C /usr/local -xzf /tmp/go.tgz && rm /tmp/go.tgz
# GOTOOLCHAIN=local: never try to download another toolchain (sandbox has no network).
ENV PATH=/usr/local/go/bin:${PATH} \
    GOTOOLCHAIN=local \
    GOFLAGS=-mod=mod \
    GOCACHE=/tmp/gocache \
    GOPATH=/tmp/gopath

# --- Python tools (CrossHair + z3, contracts, tree-sitter grammars, mypy) ------
RUN python3 -m venv /opt/pyenv \
    && /opt/pyenv/bin/pip install --no-cache-dir \
        crosshair-tool==0.0.111 \
        icontract==2.7.3 \
        hypothesis==6.170.4 \
        mypy==2.4.0 \
        tree-sitter==0.26.0 \
        tree-sitter-java==0.23.5 \
        tree-sitter-python==0.25.0 \
        tree-sitter-go==0.25.0 \
    && mkdir -p /opt/toolchain \
    && /opt/pyenv/bin/pip freeze > /opt/toolchain/pip-freeze.txt
ENV PATH=/opt/pyenv/bin:${PATH}

# --- unprivileged user that runs untrusted code ---------------------------------
RUN useradd -m -u 10001 -s /bin/bash sandbox

COPY versions.sh /opt/toolchain/versions.sh
RUN chmod a+rx /opt/toolchain/versions.sh \
    && /opt/toolchain/versions.sh > /opt/toolchain/versions.json \
    && cat /opt/toolchain/versions.json

WORKDIR /work
