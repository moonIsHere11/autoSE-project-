# Run from Linux/WSL at the repo root.
VENV   ?= $(HOME)/.venvs/cobol-verifier
PY     ?= $(VENV)/bin/python
IMAGE  ?= cobol-verifier-toolchain:0.1.0

.PHONY: help venv image lint typecheck test test-docker e2e selftest spikes runtimes clean

help:
	@echo "venv | image | lint | typecheck | test | test-docker | e2e | selftest | runtimes | spikes"

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -e ".[dev]"

image:
	docker build -t $(IMAGE) -f docker/Dockerfile docker

lint:
	$(PY) -m ruff check verifier tests tools

typecheck:
	$(PY) -m mypy

# fast unit tests (no Docker)
test:
	$(PY) -m pytest -q -m "not docker and not slow"

# tests that need the toolchain image
test-docker:
	$(PY) -m pytest -q -m "docker and not slow"

e2e:
	$(PY) -m pytest -q -m "slow"

runtimes:
	$(PY) -m tools.build_runtimes

selftest:
	$(PY) -m tools.selftest --out out/selftest --results docs/RESULTS.md

spikes:
	bash docs/spikes/s1/run.sh
	bash docs/spikes/s6/run.sh

clean:
	rm -rf out .pytest_cache .mypy_cache .ruff_cache
