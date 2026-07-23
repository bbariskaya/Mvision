COMPOSE := docker compose -f docker-compose.sprint01.yml
NATIVE_TEST_IMAGE := mvision-native-test:local
NATIVE_BUILD_DIR := $(CURDIR)/build-native-tests
NATIVE_USER := $(shell id -u):$(shell id -g)

.PHONY: infra-up infra-down phase1-s1-static phase1-s1-postgres phase1-s1-storage phase1-s1-acceptance native-test-image native-configure native-build native-test

infra-up:
	$(COMPOSE) up -d postgres minio qdrant

infra-down:
	$(COMPOSE) down

phase1-s1-static:
	$(COMPOSE) run --rm api ruff check app tests
	$(COMPOSE) run --rm api ruff format --check app tests
	$(COMPOSE) run --rm api mypy app tests

phase1-s1-postgres:
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) run --rm api pytest tests/integration/persistence -v

phase1-s1-storage:
	$(COMPOSE) run --rm api pytest tests/integration/storage tests/integration/vector -v

phase1-s1-acceptance:
	$(COMPOSE) up -d postgres minio qdrant
	$(COMPOSE) run --rm api alembic upgrade head
	$(COMPOSE) run --rm api pytest tests/integration -v
	$(COMPOSE) run --rm api alembic current
	git diff --check

native-test-image:
	docker build -f backend/pipeline/Dockerfile.native-test -t $(NATIVE_TEST_IMAGE) .

native-configure: native-test-image
	mkdir -p $(NATIVE_BUILD_DIR)
	docker run --rm --user "$(NATIVE_USER)" --entrypoint cmake \
		-v "$(CURDIR):/workspace" -w /workspace $(NATIVE_TEST_IMAGE) \
		-S /workspace/backend/pipeline -B /workspace/build-native-tests \
		-DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON

native-build: native-configure
	docker run --rm --user "$(NATIVE_USER)" --entrypoint cmake \
		-v "$(CURDIR):/workspace" -w /workspace $(NATIVE_TEST_IMAGE) \
		--build /workspace/build-native-tests --parallel "$(shell nproc)"

native-test: native-build
	docker run --rm --gpus all --user "$(NATIVE_USER)" --entrypoint ctest \
		-e LD_LIBRARY_PATH=/workspace/build-native-tests:/opt/nvidia/deepstream/deepstream/lib:/usr/local/cuda/lib64 \
		-v "$(CURDIR):/workspace" -w /workspace $(NATIVE_TEST_IMAGE) \
		--test-dir /workspace/build-native-tests --output-on-failure
	MVISION_LIVE_PROTOCOL_EXECUTABLE=$(NATIVE_BUILD_DIR)/test_live_protocol \
		backend/.venv/bin/python -m pytest \
		backend/tests/contract/test_live_protocol_parity.py -q -p no:cacheprovider
