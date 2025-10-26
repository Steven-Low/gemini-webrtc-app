 
import asyncio
import json
import logging
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse 
import numpy as np
from openwakeword.model import Model

LOGGER = logging.getLogger("wake_server")
logging.basicConfig(level=logging.INFO)

DEFAULT_WAKE_WORD_MODEL = "ok_nabu.onnx"
INNER_MODEL_DIR = "/app/models"  # External directory will map to this internally

app = FastAPI(title="WakeWord WebSocket Server")

# Initialize model eagerly to avoid per-connection overhead
try:
    user_models = [f for f in os.listdir(INNER_MODEL_DIR) if f.lower().endswith(".onnx")]
    env_model = os.getenv("WAKE_WORD_MODEL", "").strip()

    if env_model and env_model in user_models:
        model_path = os.path.join(INNER_MODEL_DIR, env_model)
    else:
        model_path = os.path.join(os.path.dirname(__file__), DEFAULT_WAKE_WORD_MODEL)

    LOGGER.info("Loading wakeword model from %s", model_path)
    wake_model = Model(wakeword_models=[model_path], inference_framework="onnx")
    LOGGER.info("Wakeword model loaded.")
except Exception as e:
    LOGGER.exception("Failed to load wakeword model: %s", e)
    wake_model = None

@app.get("/")
async def root():
    if wake_model:
        return PlainTextResponse("WakeWord WebSocket server running.")
    return PlainTextResponse("WakeWord server running, but model failed to load.", status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint that receives binary PCM int16 frames and replies with JSON:
      {"scores": {"ok_nabu": 0.83}}
    """
    await websocket.accept()
    LOGGER.info("Client connected: %s", websocket.client)

    if not wake_model:
        await websocket.send_text(json.dumps({"error": "wake model not available"}))
        await websocket.close()
        return

    try:
        while True:
            # Wait for raw bytes from client
            data = await websocket.receive()
            # The starlette receive can present three shapes; handle bytes/text/disconnect
            if "bytes" in data and data["bytes"] is not None:
                raw = data["bytes"]
            elif "text" in data and data["text"] is not None:
                # If client sends base64 or json, this server expects binary - but support fallback
                try:
                    # attempt parse bytes from JSON list
                    parsed = json.loads(data["text"])
                    if isinstance(parsed, dict) and "audio" in parsed:
                        raw = bytes(np.array(parsed["audio"], dtype=np.int16).tobytes())
                    else:
                        # Not expected format
                        await websocket.send_text(json.dumps({"error": "unsupported text payload"}))
                        continue
                except Exception:
                    await websocket.send_text(json.dumps({"error": "unsupported text payload"}))
                    continue
            elif "type" in data and data["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            else:
                # Unknown message type
                await websocket.send_text(json.dumps({"error": "unsupported message type"}))
                continue

            # Convert raw bytes to int16 numpy array
            try:
                audio_np = np.frombuffer(raw, dtype=np.int16)
            except Exception as e:
                LOGGER.exception("Failed to convert bytes to int16: %s", e)
                await websocket.send_text(json.dumps({"error": "invalid audio bytes"}))
                continue

            # Predict (run in a thread if predict is blocking)
            try:
                # Use asyncio.to_thread to avoid blocking event loop
                await asyncio.to_thread(wake_model.predict, audio_np)
                # Collect last score for each model
                scores = {}
                for mdl, score_list in wake_model.prediction_buffer.items():
          
                    if len(score_list) > 0:
                        last_score = float(score_list[-1])
                        scores[mdl] = last_score
                        if last_score > 0.7:
                            LOGGER.info(f"[DETECTED] {mdl} score={last_score:.4f}")

                
                await websocket.send_text(json.dumps({"scores": scores}))
            except Exception as e:
                LOGGER.exception("Error running prediction: %s", e)
                await websocket.send_text(json.dumps({"error": "prediction_error"}))

    except WebSocketDisconnect:
        LOGGER.info("Client disconnected: %s", websocket.client)
    except Exception as e:
        LOGGER.exception("WebSocket server error: %s", e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

