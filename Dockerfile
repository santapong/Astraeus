# Astraeus Phase 1 worker/gate image: python + git + pytest, nothing else.
# The host never runs agent-written code; it runs here, inside the container.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest

# Baked-in git identity + behaviour so no interactive prompt can ever block a
# commit/merge inside the sandbox (core.editor=true makes merge commits non-interactive).
RUN git config --global user.email "astra@astraeus.local" \
    && git config --global user.name "Astra" \
    && git config --global init.defaultBranch main \
    && git config --global core.editor true \
    && git config --global commit.gpgsign false \
    && git config --global --add safe.directory '*'

WORKDIR /workspace
