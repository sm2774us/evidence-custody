.PHONY: install check test lint type eval ts web web-dev dev demo docker up down
install:
	pip install -c constraints.txt -e ".[dev,mcp]" && cd sdk-ts && npm ci && cd ../web && npm ci
lint:
	ruff check . && ruff format --check .
type:
	mypy src
test:
	pytest --cov=custody --cov-report=term-missing
eval:
	python evals/run.py --rules-only
ts:
	cd sdk-ts && npm run typecheck && npm test
web:
	cd web && npm run check
check: lint type test eval ts web
dev:
	bash scripts/dev.sh
demo:
	custody-admin demo
docker:
	docker build -t evidence-custody:dev . && docker build -t evidence-console:dev web
up:
	docker compose up -d --build --wait
down:
	docker compose down
