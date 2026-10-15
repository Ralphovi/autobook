# The book process's test image: GnuCash 5.14 bindings on Python 3.14 (Ubuntu 26.04).
# Pinned so local runs, CI and the PDCA driver test against the same bits. Synthetic
# books only — see testenv/README.md.
FROM ubuntu:26.04@sha256:f144425ff09be612d6d9ad965196e9cdc23dae1f42110a8a11a3e9a8198759f7

ARG GNUCASH_VERSION=1:5.14-1build1
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GSETTINGS_BACKEND=memory

# python3-gnucash: the bindings. gnucash: on Ubuntu the engine libraries the bindings load
# (libgnc-engine, libgnc-app-utils …) ship only in the full package. libdbd-pgsql / libdbd-sqlite3: GnuCash's SQL backends
# (libdbi drivers). postgresql-client: pg_isready / psql for the seed and the tests.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gnucash="${GNUCASH_VERSION}" python3-gnucash="${GNUCASH_VERSION}" \
      libdbd-pgsql libdbd-sqlite3 \
      python3-pytest python3-pytest-cov \
      postgresql-client ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -c "import gnucash; from gnucash import SessionOpenMode; print('gnucash bindings OK')"

# Ubuntu images ship user `ubuntu` with UID 1000; tests run as it, never as root.
USER ubuntu
WORKDIR /src
