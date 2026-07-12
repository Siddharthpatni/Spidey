"""The ten capability modules. Each exposes a FastAPI ``router`` and, where it
does slow work, a ``register_jobs(queue)`` hook that binds its queue handlers."""
