# wake_server.py
import asyncio
import json
import logging
import os
import signal
import sys
from collections import deque
from typing import Dict, Deque, Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from openwakeword.model import Model

LOGGER = logging.getLogger("wake_server")
logging.basicConfig(level=logging.INFO)

# ----------------------------
# Config (tune via env vars)
# ----------------------------
WAKE_WORD_MODEL = os.environ.get("WAKE_WORD_MODEL", "ok_nabu.onnx")
HOST = os.environ.get("WAKE_HOST", "0.0.0.0")
PORT = int(os.environ.get("WAKE_PORT", "8001"))
SAMPLE_RATE = int(os.environ.get("WAKE_SAMPLE_RATE", "16000"))

# Window settings: 80 ms window @ 16kHz = 1280 samples (default used by Rhasspy)
OWW_MS = int(os.environ.get("WAKE_WINDOW_MS", "80"))
OWW_FRAMES = int(SAMPLE_RATE * (OWW_MS / 1000.0))

# Filter / moving-average settings (defaults taken from the Rhasspy example you posted)
ACTIVATION_THRESHOLD = float(os.environ.get("OWW_ACTIVATION_THRESHOLD", "0.7"))
DEACTIVATION_THRESHOLD = float(os.environ.get("OWW_DEACTIVATION_THRESHOLD", "0.2"))
ACTIVATION_SAMPLES = int(os.environ.get("OWW_ACTIVATION_SAMPLES", "3"))

# Minimal moving-average debug print threshold
DEBUG_PRINT_THRESHOLD = float(os.environ.get("OWW_DEBUG_PRINT_THRESHOLD", "0.1"))

# ----------------------------
# App & Model
# ----------------------------
app = FastAPI(title="WakeWord WebSocket Server (with moving-average filter)")

# load model eagerly
try:
    model_path = os.path.join(os.path.dirname(__file__), WAKE_WORD_MODEL)
    LOGGER.info("Loading wakeword model from %s", model_path)
    _MODEL: Model = Model(
        vad_threshold=0.0,  # keep default unless you want different
    )
    # Note: some Model constructors accept model paths differently; if you need to
    # pass the ONNX path explicitly, adjust below. The Rhasspy example used Model()
    # with default model names; if your Model requires wakeword_model_paths, change:
    # _MODEL = Model(wakeword_model_paths=[model_path])
    # To be safe, attempt the predict once below to ensure it works.
    LOGGER.info("Wakeword model initialized (default constructor).")
except Exception as e:
    LOGGER.exception("Failed to initialize wakeword Model: %s", e)
    _MODEL = None

if _MODEL is None:
    LOGGER.error("Wakeword model is not available. Server will return errors.")

# Per-connection state container
class ConnectionState:
    def __init__(self):
        self.buffer = []  # accumulated int16 samples (list for extend)
        # filters: wakeword -> {"samples": deque, "active": bool}
        self.filters: Dict[str, Dict[str, Any]] = {}

# helper: ensure filter exists and append confidence
def _update_filter(filters: Dict[str, Dict[str, Any]], wakeword: str, confidence: float) -> bool:
    """
    Append confidence into the per-wakeword moving-average buffer and return
    activated flag (True if rising edge).
    """
    if wakeword not in filters:
        filters[wakeword] = {
            "samples": deque([confidence], maxlen=ACTIVATION_SAMPLES),
            "active": False,
        }
    else:
        filters[wakeword]["samples"].append(confidence)

    samples: Deque = filters[wakeword]["samples"]
    moving_average = float(np.average(samples))
    activated = False

    if (not filters[wakeword]["active"]) and (moving_average >= ACTIVATION_THRESHOLD):
        filters[wakeword]["active"] = True
        activated = True
    elif filters[wakeword]["active"] and (moving_average < DEACTIVATION_THRESHOLD):
        filters[wakeword]["active"] = False

    # debug print consistent with Rhasspy example
    if moving_average > DEBUG_PRINT_THRESHOLD:
        LOGGER.debug("%-16s activated=%-5s samples=%s avg=%.3f", wakeword, activated, list(samples), moving_average)

    return activated

# ----------------------------
# Web endpoints
# ----------------------------
@app.get("/")
async def root():
    if _MODEL is not None:
        return PlainTextResponse("WakeWord WebSocket server running.")
    return PlainTextResponse("WakeWord server running, but model failed to load.", status_code=500)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Expects binary PCM int16 frames from client.
    Accumulates into OWW_FRAMES sized windows, runs detection, updates filters
    and emits JSON:
      - {"scores": {"ok_nabu": 0.83, ...}}  -- every processed window
      - {"wake": true, "keyword": "ok_nabu", "score": 0.83} -- on activation (rising edge)
    """
    await websocket.accept()
    client = websocket.client
    LOGGER.info("Client connected: %s", client)
    state = ConnectionState()

    if _MODEL is None:
        await websocket.send_text(json.dumps({"error": "wake_model_unavailable"}))
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive()

            # handle bytes/text/disconnect shapes from Starlette/ASGI
            if "bytes" in data and data["bytes"] is not None:
                raw = data["bytes"]
            elif "text" in data and data["text"] is not None:
                # Accept fallback JSON structure: {"audio": [int16,...]}
                try:
                    parsed = json.loads(data["text"])
                    if isinstance(parsed, dict) and "audio" in parsed:
                        raw = bytes(np.array(parsed["audio"], dtype=np.int16).tobytes())
                    else:
                        await websocket.send_text(json.dumps({"error": "unsupported_text_payload"}))
                        continue
                except Exception:
                    await websocket.send_text(json.dumps({"error": "unsupported_text_payload"}))
                    continue
            elif "type" in data and data["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            else:
                await websocket.send_text(json.dumps({"error": "unsupported_message_type"}))
                continue

            # Append raw bytes into buffer (convert to int16)
            try:
                samples = np.frombuffer(raw, dtype=np.int16)
            except Exception as e:
                LOGGER.exception("Invalid audio bytes: %s", e)
                await websocket.send_text(json.dumps({"error": "invalid_audio_bytes"}))
                continue

            # Extend connection buffer
            state.buffer.extend(samples.tolist())

            # Process windows while enough samples
            while len(state.buffer) >= OWW_FRAMES:
                window = np.asarray(state.buffer[:OWW_FRAMES], dtype=np.int16)
                # drop processed samples
                state.buffer = state.buffer[OWW_FRAMES:]

                # Run predict on thread (Model.predict can be blocking)
                try:
                    prediction = await asyncio.to_thread(_MODEL.predict, window)
                    # prediction is expected like {'ok_nabu': 0.82, ...}
                    if not isinstance(prediction, dict):
                        # some Model implementations may populate internal buffer instead
                        # If so, attempt to read prediction_buffer attribute (fallback)
                        try:
                            pb = getattr(_MODEL, "prediction_buffer", {})
                            prediction = {k: float(v[-1]) for k, v in pb.items() if v}
                        except Exception:
                            prediction = {}
                except Exception as e:
                    LOGGER.exception("Prediction error: %s", e)
                    prediction = {}

                # Always send scores for this window so clients can visualize if desired
                try:
                    await websocket.send_text(json.dumps({"scores": prediction}))
                except Exception:
                    # If client dropped, break outer loop and close
                    raise

                # Update filters and send wake event if rising edge
                for wakeword, confidence in list(prediction.items()):
                    try:
                        activated = _update_filter(state.filters, wakeword, float(confidence))
                        if activated and wakeword:
                            # Emit single wake event (rising edge)
                            payload = {"wake": True, "keyword": wakeword, "score": float(confidence)}
                            LOGGER.info("Wake detected: %s (score=%.3f)", wakeword, float(confidence))
                            await websocket.send_text(json.dumps(payload))
                            # Note: do NOT clear filter here; the moving-average logic will keep 'active'
                            # until it drops below deactivation threshold.
                    except Exception:
                        LOGGER.exception("Error handling wakeword %s", wakeword)

    except WebSocketDisconnect:
        LOGGER.info("Client disconnected: %s", client)
    except Exception as e:
        LOGGER.exception("WebSocket server error: %s", e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        LOGGER.info("Connection closed: %s", client)

# Optional: graceful shutdown when running directly
if __name__ == "__main__":
    import uvicorn

    LOGGER.info("Starting wake_server via uvicorn on %s:%d (OWW_FRAMES=%d)", HOST, PORT, OWW_FRAMES)
    uvicorn.run("wake_server:app", host=HOST, port=PORT, log_level="info")
