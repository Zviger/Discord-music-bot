.PHONY: install sync lock debug build up down lint format

install:
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "Add $$HOME/.cargo/bin to your PATH"

sync:
	uv sync
	
lock:
	uv lock

debug:
	docker-compose -f docker-compose.debug.yml up --build

build:
	docker-compose build

up:
	docker-compose up -d 

down:
	docker-compose down

logs:
	docker-compose logs -f

lint:
	uv run ruff format --diff
	uv run ruff check
	uv run mypy .

format:
	uv run ruff format
	uv run ruff check --fix
