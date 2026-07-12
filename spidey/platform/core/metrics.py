"""In-process metrics with Prometheus text exposition — no client library.

Counters and gauges keyed by ``name{label="value",...}``. The /metrics endpoint
calls :func:`render`; Prometheus/Grafana scrape it as-is.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

_lock = threading.Lock()
_counters: Dict[str, float] = {}
_gauges: Dict[str, float] = {}
_started = time.time()


def _key(name: str, labels: Optional[Dict[str, str]]) -> str:
    if not labels:
        return name
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"


def inc(name: str, labels: Optional[Dict[str, str]] = None, by: float = 1) -> None:
    k = _key(name, labels)
    with _lock:
        _counters[k] = _counters.get(k, 0) + by


def gauge(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    with _lock:
        _gauges[_key(name, labels)] = value


def snapshot() -> Dict[str, float]:
    with _lock:
        return {**_counters, **_gauges}


def render() -> str:
    lines = [
        "# HELP spidey_uptime_seconds Seconds since the platform started.",
        "# TYPE spidey_uptime_seconds gauge",
        f"spidey_uptime_seconds {time.time() - _started:.0f}",
    ]
    with _lock:
        for k in sorted(_counters):
            base = k.split("{")[0]
            lines.append(f"# TYPE {base} counter")
            lines.append(f"{k} {_counters[k]:g}")
        for k in sorted(_gauges):
            base = k.split("{")[0]
            lines.append(f"# TYPE {base} gauge")
            lines.append(f"{k} {_gauges[k]:g}")
    return "\n".join(lines) + "\n"
