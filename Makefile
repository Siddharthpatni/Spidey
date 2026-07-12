# Spidey — common tasks. Override variables inline, e.g.:
#   make run TASK="add type hints to utils.py" MODEL=qwen2.5-coder:7b
#   make eval MODELS=qwen2.5-coder:3b,spidey-sft,spidey-brain

MODEL  ?= gemma4:12b
TASK   ?= List the files here and summarize the project.
MODELS ?= qwen2.5-coder:3b,spidey-brain
STEPS  ?= 60
PORT   ?= 8000

.PHONY: install setup serve run eval web-build finetune dpo clean

install:            ## Install the agent + web server + offline voice (editable)
	pip install -e ".[server,voice]"

setup:              ## Download an open-weight model for fully offline use
	spidey setup --model $(MODEL)

serve:              ## Start the web UI (chat + live reasoning web)
	spidey serve --port $(PORT)

sandbox:            ## Run Spidey boxed in Docker — only ./workspace is reachable, host data is safe
	@command -v openssl >/dev/null && export SPIDEY_TOKEN=$${SPIDEY_TOKEN:-$$(openssl rand -hex 16)}; \
	echo "▶ Sandbox token: $$SPIDEY_TOKEN"; \
	echo "▶ Open  http://localhost:8000/?token=$$SPIDEY_TOKEN  once it's up"; \
	SPIDEY_TOKEN=$$SPIDEY_TOKEN docker compose up --build

sandbox-down:       ## Stop the sandbox (data in the spidey-home volume is kept)
	docker compose down

run:                ## Run a task: make run TASK="..." MODEL=...
	spidey run "$(TASK)" --model $(MODEL)

eval:               ## Compare models: make eval MODELS=a,b,c (first = baseline)
	python eval/run_eval.py --models $(MODELS)

web-build:          ## Rebuild the frontend into spidey/server/static
	cd web && npm install && npm run build

finetune:           ## Stage 1 — SFT (run on a GPU): make finetune STEPS=60
	cd training && python finetune.py --steps $(STEPS)

dpo:                ## Stage 2 — DPO decision training (run on a GPU, after finetune)
	cd training && python dpo_finetune.py --adapter outputs --steps $(STEPS)

clean:              ## Remove caches and training artifacts
	rm -rf outputs outputs-dpo spidey-brain spidey-brain-dpo **/__pycache__ *.egg-info
