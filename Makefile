.PHONY: build install uninstall test lint format ui venv clean

PY := .venv/bin/python
ZIP := dist/calpdf.zip
CALPDF_SRC ?= ../calpdf/src

venv:
	uv venv --allow-existing --system-site-packages --python python3 .venv
	uv pip install --python $(PY) pytest ruff

build:
	python3 build.py

install: build
	calibre-customize -a $(ZIP)

uninstall:
	calibre-customize -r CalPDF

test: venv
	PYTHONPATH=$(CALPDF_SRC) $(PY) -m pytest -q

lint: venv
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format: venv
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

ui: venv
	PYTHONPATH=$(CALPDF_SRC) $(PY) tools/screenshot.py

clean:
	rm -rf build dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
