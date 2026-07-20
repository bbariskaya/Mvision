COMPOSE := docker compose -f docker-compose.sprint01.yml

.PHONY: infra-up infra-down phase1-s1-static phase1-s1-postgres phase1-s1-storage phase1-s1-acceptance

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
