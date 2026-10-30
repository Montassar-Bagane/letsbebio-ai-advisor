# Recommendation engine — common tasks.
# Run `make` with no argument to see what is available.

SERVICE := service
PY      := python3

.DEFAULT_GOAL := help

help:                ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:               ## one-shot setup: database user, virtualenv, .env
	@bash setup.sh

install: setup       ## alias for setup

test:                ## check every part of the system (API must be running)
	@bash test.sh

enable-agent:        ## add an API key and switch the agent on: make enable-agent KEY=gsk_...
	@test -n "$(KEY)" || { echo "Usage: make enable-agent KEY=gsk_your_key"; exit 1; }
	@sed -i 's|^ENABLE_INTERPRET=.*|ENABLE_INTERPRET=true|' $(SERVICE)/.env
	@sed -i 's|^LLM_API_KEY=.*|LLM_API_KEY=$(KEY)|' $(SERVICE)/.env
	@echo "Agent enabled. Restart the API (Ctrl+C then 'make run')."

enable-semantic:     ## install embeddings (CPU-only) and switch semantic search on
	@# PyTorch defaults to its CUDA build: ~2.5 GB of GPU libraries that are
	@# useless here, since 600 embeddings run fine on a CPU. The CPU index
	@# below cuts the download to roughly a fifth of that.
	@df -h . | tail -1 | awk '{print "Free space: " $$4}'
	@echo "Installing CPU-only PyTorch (about 500 MB)..."
	cd $(SERVICE) && .venv/bin/pip install --no-cache-dir \
	  --index-url https://download.pytorch.org/whl/cpu torch
	cd $(SERVICE) && .venv/bin/pip install --no-cache-dir sentence-transformers numpy
	@sed -i 's|^EMBED_BACKEND=.*|EMBED_BACKEND=local|' $(SERVICE)/.env
	@echo ""
	@echo "Semantic search enabled. Restart the API - the first run downloads"
	@echo "the embedding model (about 470 MB) and indexes the catalogue."

models:              ## list models your provider offers, marking tool support
	@# The agent needs tool calling. Providers mix tool-capable and
	@# text-only models on the same endpoint, and retire them without notice.
	@cd $(SERVICE) && set -a && . ./.env && set +a && \
	  curl -s "$$LLM_BASE_URL/models" -H "Authorization: Bearer $$LLM_API_KEY" \
	  | .venv/bin/python ../scripts/list_models.py \
	  || echo '  Could not list models - check LLM_BASE_URL and LLM_API_KEY'
	@echo ""
	@echo "Pick one marked [tools], then:  make set-model MODEL=<id>"
set-model:           ## switch the language model: make set-model MODEL=llama-3.1-8b-instant
	@test -n "$(MODEL)" || { echo "Usage: make set-model MODEL=<id>   (see 'make models')"; exit 1; }
	@sed -i 's|^LLM_MODEL=.*|LLM_MODEL=$(MODEL)|' $(SERVICE)/.env
	@echo "Model set to $(MODEL). Restart the API."

free-space:          ## reclaim disk space after a failed install
	-cd $(SERVICE) && .venv/bin/pip cache purge
	-rm -rf $$HOME/.cache/pip
	@df -h . | tail -1 | awk '{print "Free space now: " $$4}'

run:                 ## start the API on port 8000
	cd $(SERVICE) && set -a && . ./.env && set +a && \
	  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:                 ## start the API with auto-reload (development only)
	cd $(SERVICE) && set -a && . ./.env && set +a && \
	  .venv/bin/uvicorn app.main:app --port 8000 --reload

health:              ## check that the API is up
	@curl -s localhost:8000/health | $(PY) -m json.tool

demo:                ## serve the standalone demo page on port 8080
	cd demo && $(PY) -m http.server 8080

validate:            ## run the 22 validation profiles and build the review sheet
	cd validation && $(PY) validate.py

compare:             ## compare the current engine against the saved baseline
	cd validation && $(PY) validate.py --compare

baseline:            ## save the current results as the new reference
	cd validation && $(PY) validate.py --save-baseline

plugin:              ## package the WordPress plugin for upload
	@# Python's zipfile is used rather than the zip command: zip is not
	@# installed by default on a minimal WSL image, and requiring an apt
	@# install to package a plugin is a poor trade.
	@$(PY) scripts/make_plugin.py

report:              ## build the PFE report PDF
	cd docs/pfe-report-latex && latexmk -pdf main.tex
	@echo "Built docs/pfe-report-latex/main.pdf"

clean:               ## remove generated files
	rm -f reco-engine.zip
	rm -f $(SERVICE)/embeddings_cache.json
	rm -f validation/validation_run.json
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	cd docs/pfe-report-latex && latexmk -c 2>/dev/null || true

.PHONY: help setup install test enable-agent enable-semantic models set-model free-space run dev health demo validate compare baseline plugin report clean
