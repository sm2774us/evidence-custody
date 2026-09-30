.PHONY: install check test lint type eval ts demo docker
install:
	pip install -c constraints.txt -e ".[dev,mcp]" && cd sdk-ts && npm ci
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
check: lint type test eval ts
demo:
	custody-admin demo
docker:
	docker build -t evidence-custody:dev .
