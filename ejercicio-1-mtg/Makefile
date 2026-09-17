.PHONY: install ingest api ui test lint

install:
	python -m pip install -e ".[dev,ingest]"

ingest:
	python -m mtg_assistant.rag.ingest $(SOURCE)

api:
	uvicorn mtg_assistant.api:app --reload --port 8000

ui:
	streamlit run src/mtg_assistant/ui.py

test:
	pytest

lint:
	ruff check src tests scripts
