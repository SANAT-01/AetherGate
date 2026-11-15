.PHONY: install migrate up down test test-cov lint format typecheck

install:
	pip install -e ".[dev]"

migrate:
	docker compose run --rm web python manage.py migrate

up:
	docker compose up

down:
	docker compose down

test:
	pytest

test-cov:
	pytest --cov

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy apps config
