.PHONY: test test-unit test-integration test-e2e test-chaos demo-sync convergence-proof clean

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

test: test-unit test-integration

test-unit:
	$(PYTEST) sync/tests/unit -v

test-integration:
	$(PYTEST) sync/tests/integration -v

test-e2e:
	$(PYTEST) sync/tests/e2e -v

test-chaos:
	$(PYTEST) sync/tests/chaos -v

demo-sync:
	docker compose -f infra/docker-compose.sync-only.yml up --build

convergence-proof:
	$(PYTEST) sync/tests/chaos/test_convergence.py -v

clean:
	docker compose -f infra/docker-compose.sync-only.yml down -v
