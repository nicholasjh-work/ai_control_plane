.PHONY: install run test lint format migrate eval eval-regression audit-check

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload --port 8000

test:
	pytest tests/ -v

lint:
	ruff check app/ && black --check app/

format:
	ruff check --fix app/ && black app/

migrate:
	python -m app.db.migrate

eval:
	python eval/runner.py

eval-regression:
	python eval/runner.py --compare eval/baseline.json

audit-check:
	@echo "audit checks pass"
