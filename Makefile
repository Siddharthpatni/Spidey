# Spidey — common tasks. Override variables inline, e.g.:
#   make run TASK="add type hints to utils.py" MODEL=qwen2.5-coder:7b
#   make eval MODELS=qwen2.5-coder:3b,spidey-sft,spidey-brain

MODEL  ?= qwen2.5-coder:7b
TASK   ?= List the files here and summarize the project.
MODELS ?= qwen2.5-coder:3b,spidey-brain
STEPS  ?= 60
PORT   ?= 8000

.PHONY: install setup demo serve run eval web-build finetune dpo clean

install:            ## Install the agent + web server (editable)
	pip install -e ".[server]"

setup:              ## Download an open-weight model for fully offline use
	spidey setup --model $(MODEL)

demo:               ## Run the offline demo (no Ollama/GPU needed)
	python examples/demo_offline.py

serve:              ## Start the web UI (chat + live reasoning web)
	spidey serve --port $(PORT)

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
