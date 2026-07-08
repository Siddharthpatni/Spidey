#!/usr/bin/env bash
# Spidey — one-script setup. After this: `spidey up` starts everything.
#   curl -fsSL https://raw.githubusercontent.com/Siddharthpatni/Spidey/main/install.sh | bash
# or, from a clone:  ./install.sh
set -euo pipefail

say()  { printf "\033[1;36m● %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }

# 0. Get the code (when piped from curl outside a clone)
if [ ! -f "pyproject.toml" ]; then
  say "Cloning Spidey…"
  git clone https://github.com/Siddharthpatni/Spidey && cd Spidey
fi

# 1. Python venv + the package (server + offline voice)
command -v python3 >/dev/null || { warn "python3 is required — install it first."; exit 1; }
say "Installing Spidey (server + voice)…"
python3 -m venv .venv
.venv/bin/pip -q install --upgrade pip
.venv/bin/pip -q install -e ".[server,voice]"

# 2. Ollama — the free offline model runtime
if ! command -v ollama >/dev/null; then
  if command -v brew >/dev/null; then
    say "Installing Ollama…"
    brew install ollama
  else
    warn "Install Ollama from https://ollama.com/download (free), then re-run this script."
    exit 1
  fi
fi

# 3. Offline voice model (~40 MB) — "Hey Spidey"
say "Setting up offline voice…"
.venv/bin/spidey setup --voice || true

# 4. Done — the brain (one-time model download) happens on first `spidey up`
cat <<'EOF'

  🕷  Spidey is installed. Start everything with ONE command:

      .venv/bin/spidey up

  (add `--https --token <secret> --host 0.0.0.0` to use it from your phone)
  First start downloads the brain (~7.6 GB, once). After that: fully offline.
EOF
