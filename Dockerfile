# Spidey — containerized web UI.
#
#   docker build -t spidey .
#   docker run -p 8000:8000 spidey
#
# Works as-is on Railway / Render / Fly.io (they set $PORT). Users bring their own
# Claude/Gemini/GPT keys through the browser; to use Ollama from inside the container,
# point the Custom provider at a reachable Ollama URL.
#
# ⚠ Spidey executes shell commands as an agent. The container is its sandbox — do not
# mount host paths you care about, and don't expose a public instance without auth.

FROM node:22-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ .
COPY spidey/ /spidey-pkg/spidey/
RUN sed -i "s#outDir: '../spidey/server/static'#outDir: '/spidey-pkg/spidey/server/static'#" vite.config.js \
    && npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY spidey/ spidey/
COPY --from=web /spidey-pkg/spidey/server/static/ spidey/server/static/
RUN pip install --no-cache-dir ".[server]"

# The agent works inside /workspace — mount a volume here if you want persistence.
RUN useradd -m spidey && mkdir /workspace && chown spidey:spidey /workspace
USER spidey
WORKDIR /workspace

EXPOSE 8000
CMD ["sh", "-c", "spidey serve --host 0.0.0.0 --port ${PORT:-8000} --workdir /workspace"]
