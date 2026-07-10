"""Offline voice for Spidey: wake word + speech-to-text, 100% on-device.

The browser captures the microphone and streams raw PCM (16 kHz, mono, 16-bit)
over a WebSocket. This module turns that stream into events using Vosk — a small
open-source speech recognizer that runs entirely on the user's machine. No audio
ever leaves the device.

Two listening modes:
    wake    hands-free. A lightweight recognizer listens continuously for
            "hey spidey"; once heard, the next utterance is captured as the task.
    direct  push-to-talk. Everything said is transcribed immediately.

Text-to-speech is deliberately NOT here: the browser's ``speechSynthesis`` API
uses the OS's local voices (offline on macOS/Windows/most Linux), so the reply
is spoken without any extra downloads.

The recognizer model (~40 MB) is fetched once by ``spidey setup --voice`` into
``~/.spidey/models/`` and used offline forever after.
"""

from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono

MODELS_DIR = Path.home() / ".spidey" / "models"
VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"

# The small model has no "spidey" in its vocabulary, so it hears the wake word
# as one of these near neighbours. Any (first, second) adjacent pair counts.
WAKE_FIRST = {"hey", "hi", "a", "hate", "he", "they", "okay"}
WAKE_SECOND = {"spidey", "spider", "spiders", "speedy", "spidy", "speed",
               "spitting", "spitty", "spit", "spiky", "spied"}

WAKE_TIMEOUT_S = 8.0     # seconds of silence after the wake word before dozing off
MAX_UTTERANCE_S = 30.0   # hard cap on a single spoken command


def model_path() -> Path:
    return MODELS_DIR / VOSK_MODEL_NAME


def vosk_installed() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except ImportError:
        return False


def model_downloaded() -> bool:
    return (model_path() / "am").is_dir() or (model_path() / "conf").is_dir()


def voice_status() -> Dict[str, Any]:
    """What's missing (if anything) for offline voice to work."""
    ok = vosk_installed() and model_downloaded()
    status: Dict[str, Any] = {
        "available": ok,
        "vosk_installed": vosk_installed(),
        "model_downloaded": model_downloaded(),
        "model": VOSK_MODEL_NAME,
    }
    if not status["vosk_installed"]:
        status["hint"] = 'Install the voice extras:  pip install -e ".[voice]"'
    elif not status["model_downloaded"]:
        status["hint"] = "Download the offline speech model:  spidey setup --voice"
    return status


def download_model(quiet: bool = False) -> Path:
    """Fetch the Vosk model zip once and unpack it under ~/.spidey/models."""
    import requests

    dest = model_path()
    if model_downloaded():
        if not quiet:
            print(f"✓ Speech model already at {dest}")
        return dest

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_DIR / f"{VOSK_MODEL_NAME}.zip"
    if not quiet:
        print(f"● Downloading {VOSK_MODEL_NAME} (~40 MB, one time — voice runs offline after this)…")
    with requests.get(VOSK_MODEL_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(MODELS_DIR)
    zip_path.unlink(missing_ok=True)
    if not quiet:
        print(f"✓ Speech model ready at {dest}")
    return dest


# One Vosk model shared by every session — it's read-only and ~300 MB in RAM
# would be silly per-connection.
_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)
            _model = Model(str(model_path()))
        return _model


def _heard_wake(text: str) -> bool:
    words = text.lower().split()
    for first, second in zip(words, words[1:]):
        if first in WAKE_FIRST and second in WAKE_SECOND:
            return True
    return False


def _strip_wake(text: str) -> str:
    """Drop a leading wake phrase so 'hey spidey list my files' -> 'list my files'."""
    words = text.split()
    if len(words) >= 2 and words[0].lower() in WAKE_FIRST and words[1].lower() in WAKE_SECOND:
        return " ".join(words[2:])
    return text


class VoiceSession:
    """Feeds PCM chunks to Vosk and yields wake/partial/utterance events.

    States: ``listening`` (wake mode only — waiting for "hey spidey"),
    ``capturing`` (recording the command until end-of-speech). Time is measured
    in audio fed, not wall clock, so laggy networks don't cut people off.
    """

    def __init__(self, mode: str = "wake") -> None:
        from vosk import KaldiRecognizer

        model = get_model()
        self.mode = mode
        self.rec = KaldiRecognizer(model, SAMPLE_RATE)
        self.state = "listening" if mode == "wake" else "capturing"
        self._captured_s = 0.0   # audio seconds since capture started
        self._had_speech = False
        self._last_heard = ""    # last wake-mode partial we told the client about

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._restart("listening" if mode == "wake" else "capturing")

    def _restart(self, state: str) -> None:
        self.rec.Reset()
        self.state = state
        self._captured_s = 0.0
        self._had_speech = False

    def feed(self, pcm: bytes) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        seconds = len(pcm) / BYTES_PER_SECOND

        final_text: Optional[str] = None
        if self.rec.AcceptWaveform(pcm):
            final_text = (json.loads(self.rec.Result()).get("text") or "").strip()
        partial = (json.loads(self.rec.PartialResult()).get("partial") or "").strip()

        if self.state == "listening":
            # Tell the client what the recognizer hears while waiting for the
            # wake word — the difference between "broken" and "it heard
            # 'hey sweetie'" is everything when debugging a mic.
            heard_now = partial or (final_text or "")
            if heard_now != self._last_heard:
                self._last_heard = heard_now
                events.append({"type": "heard", "text": heard_now[-60:]})
            heard = (final_text and _heard_wake(final_text)) or _heard_wake(partial)
            if heard:
                # If the command rode in on the same breath, keep its tail.
                tail = _strip_wake(final_text) if final_text else ""
                events.append({"type": "wake"})
                self._restart("capturing")
                if tail:
                    events.append({"type": "utterance", "text": tail})
                    self._restart("listening")
            return events

        # capturing
        self._captured_s += seconds
        if partial:
            self._had_speech = True
            events.append({"type": "partial", "text": partial})

        if final_text is not None:
            text = _strip_wake(final_text)
            if text:
                events.append({"type": "utterance", "text": text})
                if self.mode == "wake":
                    events.append({"type": "sleep"})
                    self._restart("listening")
                else:
                    self._restart("capturing")
                return events
            # Silence chunk — in wake mode, doze off if nothing was ever said.
            if self.mode == "wake" and not self._had_speech and self._captured_s > WAKE_TIMEOUT_S:
                events.append({"type": "sleep"})
                self._restart("listening")
                return events

        if self.state == "capturing" and self._captured_s > MAX_UTTERANCE_S:
            text = _strip_wake((json.loads(self.rec.FinalResult()).get("text") or "").strip())
            if text:
                events.append({"type": "utterance", "text": text})
            if self.mode == "wake":
                events.append({"type": "sleep"})
                self._restart("listening")
            else:
                self._restart("capturing")
        return events
