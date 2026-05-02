.PHONY: test test-unit test-integration test-e2e test-chaos demo-sync convergence-proof clean \
        dev-image test-unit-docker test-integration-docker test-e2e-docker lint-docker test-docker

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

DEV_IMAGE ?= sync-dev:latest
DOCKER_RUN ?= docker run --rm -v $(CURDIR):/app -w /app
DOCKER_RUN_TC ?= docker run --rm -v $(CURDIR):/app -w /app -v /var/run/docker.sock:/var/run/docker.sock -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal --add-host=host.docker.internal:host-gateway

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

dev-image:
	docker build -f sync/Dockerfile.dev -t $(DEV_IMAGE) .

test-unit-docker: dev-image
	$(DOCKER_RUN) $(DEV_IMAGE) pytest sync/tests/unit -v

test-integration-docker: dev-image
	$(DOCKER_RUN_TC) $(DEV_IMAGE) pytest sync/tests/integration -v

test-e2e-docker: dev-image
	$(DOCKER_RUN_TC) $(DEV_IMAGE) pytest sync/tests/e2e -v

lint-docker: dev-image
	$(DOCKER_RUN) $(DEV_IMAGE) ruff check sync/

test-docker: test-unit-docker test-integration-docker
