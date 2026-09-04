session-init:
	bash scripts/session-init.sh

test:
	python -m pytest

lint:
	ruff check src tests

compile:
	python -m compileall -q src tests
