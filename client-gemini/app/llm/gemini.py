import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import av
from av import AudioResampler
from aiortc.contrib.media import MediaStreamError
from google import genai
from google.genai import types
from openwakeword.model import Model

from app.config.constants import (
    CHUNK_DURATION_MS,
    CHUNK_SIZE_BYTES,
    CONF_CHAT_MODEL,
    GEMINI_SAMPLE_RATE,
    GEMINI_WEBRTC_SAMPLE_RATE,
)
from app.llm.base import BaseLLMManager
from app.services.homeassistant_api import turn_off_light, turn_on_light

LOGGER = logging.getLogger(__name__)

_PIPER_VOICE = None
_PIPER_VOICE_LOCK = threading.Lock()

WAKE_WORD_MODEL = "ok_nabu.onnx"
WAKE_BUFFER = 560
WAKE_THRESHOLD = 0.6
DEBOUNCE_TIME = 2
SILENCE_DURATION_SECONDS = 0.9
NO_SPEECH_TIMEOUT_SECONDS = 6
MIN_SPEECH_SECONDS = 0.18
MAX_UTTERANCE_SECONDS = 30
SPEECH_THRESHOLD = 350
MAX_TOOL_ROUNDS = 5
WAKE_CUE_FREQUENCY = 880
WAKE_CUE_DURATION_SECONDS = 0.12
PROCESSING_CUE_FREQUENCIES = (660, 990)
PROCESSING_CUE_TONE_SECONDS = 0.10
PROCESSING_CUE_GAP_SECONDS = 0.045

GEMINI_SYSTEM_PROMPT = """
You are a helpful, informative AI assistant. Answer in English, be concise when
speaking aloud. You can control the user's Home Assistant lights with the
provided functions. You do not have live web search; say when an answer needs
current information that you cannot verify.
When the user says goodbye or asks you to sleep, call good_bye.
"""

GEMINI_TOOLS = [
    {
        "type": "function",
        "name": "turn_on_the_lights",
        "description": "Turn on the configured Home Assistant lights.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "turn_off_the_lights",
        "description": "Turn off the configured Home Assistant lights.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "good_bye",
        "description": "Put the voice assistant into wake-word standby.",
        "parameters": {"type": "object", "properties": {}},
    },
]


class GeminiClientManager(BaseLLMManager):
    """Wake-word voice client using Gemini's request/response Interactions API."""

    def __init__(self, remote_user_id):
        super().__init__()
        self.llm_name = "gemini"
        self.remote_user_id = remote_user_id
        self.tasks = []
        self.audio_playback_queue = asyncio.Queue(maxsize=100)
        self.raw_audio_to_play_queue = asyncio.Queue(maxsize=10)
        self.wakeword_model = None
        self.wake_buffer = np.array([], dtype=np.int16)
        self.last_wake_time = 0
        self.is_wake = asyncio.Event()
        self.client = None
        self.interaction_id = None

    async def start_video_processing(self, webrtc_track):
        asyncio.create_task(self._drain_track(webrtc_track))

    async def _drain_track(self, track):
        LOGGER.info("Skipping WebRTC video tracks.")
        try:
            while True:
                await track.recv()
        except (MediaStreamError, asyncio.CancelledError):
            pass

    async def start_session(self, webrtc_track):
        LOGGER.info("Starting Gemini Interactions API voice session for %s", self.remote_user_id)
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is required to start the Gemini voice session")

        self.wakeword_model = Model(
            wakeword_model_paths=[
                os.path.join(os.path.dirname(__file__), "../assets/openwakeword", WAKE_WORD_MODEL)
            ]
        )
        # A request that hits quota should fail immediately instead of silently
        # resending the same audio several times through the SDK's default retries.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                # This SDK maps attempts to retries internally despite the
                # public field description. The legacy HTTP client normalizes
                # 0 to 1, so we also reset the generated Interactions retry
                # policy after constructing the client below.
                retry_options=types.HttpRetryOptions(attempts=0)
            ),
        )
        self.client._api_client._http_options.retry_options.attempts = 0
        interactions = self.client.interactions
        interactions.sdk_configuration.retry_config.max_retries = 0
        send_task = asyncio.create_task(self._send_to_gemini_task(webrtc_track))
        playback_task = asyncio.create_task(self._playback_manager_task())
        self.tasks = [send_task, playback_task]
        try:
            await send_task
        except asyncio.CancelledError:
            pass
        except Exception:
            LOGGER.exception("Gemini voice session failed")
        finally:
            await self.stop_session()

    async def stop_session(self):
        current = asyncio.current_task()
        tasks = list(self.tasks)
        self.tasks = []
        for task in tasks:
            if task is not current and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in tasks if task is not current), return_exceptions=True
        )
        for queue in (self.raw_audio_to_play_queue, self.audio_playback_queue):
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
        if self.client:
            self.client.close()
            self.client = None
        self.interaction_id = None
        LOGGER.info("Gemini voice session cleaned up")

    async def _playback_manager_task(self):
        try:
            while True:
                pcm = await self.raw_audio_to_play_queue.get()
                try:
                    for offset in range(0, len(pcm), CHUNK_SIZE_BYTES):
                        chunk = pcm[offset : offset + CHUNK_SIZE_BYTES]
                        if chunk:
                            await self.audio_playback_queue.put(chunk)
                            await asyncio.sleep(CHUNK_DURATION_MS / 1000)
                finally:
                    self.raw_audio_to_play_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _send_to_gemini_task(self, track):
        resampler = AudioResampler(format="s16", layout="mono", rate=GEMINI_SAMPLE_RATE)
        utterance_frames = []
        speech_samples = 0
        silence_samples = 0
        active_samples = 0
        silence_limit = int(GEMINI_SAMPLE_RATE * SILENCE_DURATION_SECONDS)

        async def finish_utterance():
            nonlocal utterance_frames, speech_samples, silence_samples, active_samples
            if utterance_frames:
                captured = np.concatenate(utterance_frames).astype(np.int16)
                if speech_samples >= int(GEMINI_SAMPLE_RATE * MIN_SPEECH_SECONDS):
                    LOGGER.info("Speech ended; playing processing cue for %s", self.remote_user_id)
                    await self.raw_audio_to_play_queue.put(
                        self._make_processing_sound()
                    )
                    await self._process_utterance(captured.tobytes())
                else:
                    LOGGER.info("Wake word heard but no request speech was captured")
            self.is_wake.clear()
            utterance_frames = []
            speech_samples = silence_samples = active_samples = 0
            self.wake_buffer = np.array([], dtype=np.int16)

        try:
            while True:
                try:
                    frame = await asyncio.wait_for(
                        track.recv(), timeout=SILENCE_DURATION_SECONDS
                    )
                except asyncio.TimeoutError:
                    if self.is_wake.is_set():
                        LOGGER.info(
                            "No incoming audio frames for %.1f seconds; ending utterance",
                            SILENCE_DURATION_SECONDS,
                        )
                        silence_samples = max(silence_samples, silence_limit)
                        await finish_utterance()
                    continue

                for converted in resampler.resample(frame):
                    samples = converted.to_ndarray().astype(np.int16).reshape(-1)
                    if not self.is_wake.is_set():
                        self.wake_buffer = np.concatenate((self.wake_buffer, samples))
                        while len(self.wake_buffer) >= WAKE_BUFFER:
                            chunk = self.wake_buffer[:WAKE_BUFFER]
                            self.wake_buffer = self.wake_buffer[WAKE_BUFFER:]
                            await asyncio.to_thread(self.wakeword_model.predict, chunk)
                            detected = any(
                                len(scores) > 0 and scores[-1] > WAKE_THRESHOLD
                                for scores in self.wakeword_model.prediction_buffer.values()
                            )
                            if detected:
                                now = asyncio.get_running_loop().time()
                                if now - self.last_wake_time >= DEBOUNCE_TIME:
                                    LOGGER.info("Wake word detected for %s", self.remote_user_id)
                                    self.is_wake.set()
                                    self.last_wake_time = now
                                    self.wakeword_model.prediction_buffer.clear()
                                    self.raw_audio_to_play_queue.put_nowait(
                                        self._make_wake_confirmation_sound()
                                    )
                                    utterance_frames = [samples]
                                    active_samples = len(samples)
                                    break
                                LOGGER.debug("Ignoring debounced wake word")
                    if not self.is_wake.is_set():
                        continue

                    if not utterance_frames:
                        utterance_frames.append(samples)
                    elif utterance_frames[-1] is not samples:
                        utterance_frames.append(samples)

                    frame_rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                    frame_samples = len(samples)
                    active_samples += frame_samples
                    if frame_rms >= SPEECH_THRESHOLD:
                        speech_samples += frame_samples
                        silence_samples = 0
                    else:
                        silence_samples += frame_samples

                    no_speech_limit = int(GEMINI_SAMPLE_RATE * NO_SPEECH_TIMEOUT_SECONDS)
                    max_utterance = int(GEMINI_SAMPLE_RATE * MAX_UTTERANCE_SECONDS)
                    if (
                        silence_samples >= silence_limit
                        or active_samples >= max_utterance
                        or (speech_samples == 0 and active_samples >= no_speech_limit)
                    ):
                        await finish_utterance()
        except MediaStreamError:
            LOGGER.info("User audio track ended")
        except asyncio.CancelledError:
            pass

    async def _process_utterance(self, pcm_audio):
        wav_audio = self._pcm_to_wav(pcm_audio, GEMINI_SAMPLE_RATE)
        self._save_debug_audio(wav_audio)
        LOGGER.info("Sending %d bytes of voice input to Gemini", len(wav_audio))
        try:
            text, should_sleep = await asyncio.to_thread(self._request_response, wav_audio)
            if not text:
                LOGGER.info("Gemini returned no speech text")
                return
            LOGGER.info("Gemini response [%s]: %s", self.remote_user_id, text)
            speech_pcm = await asyncio.to_thread(self._synthesize_speech, text)
            if speech_pcm:
                await self.raw_audio_to_play_queue.put(speech_pcm)
            if should_sleep:
                self.is_wake.clear()
        except Exception:
            LOGGER.exception("Failed to process voice request for %s", self.remote_user_id)
            try:
                error_pcm = await asyncio.to_thread(
                    self._synthesize_speech,
                    "I couldn't get a response from Gemini. Please check the API quota.",
                )
                if error_pcm:
                    await self.raw_audio_to_play_queue.put(error_pcm)
            except Exception:
                LOGGER.exception("Could not play the local Gemini error message")

    def _save_debug_audio(self, wav_audio):
        """Save a captured utterance when debug audio capture is enabled."""
        debug_dir = os.getenv("GEMINI_DEBUG_AUDIO_DIR")
        if not debug_dir:
            return

        safe_user_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(self.remote_user_id))
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        audio_path = Path(debug_dir) / f"utterance_{safe_user_id}_{timestamp}.wav"
        try:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(wav_audio)
            LOGGER.info("Saved debug voice input to %s", audio_path)
        except OSError:
            LOGGER.exception("Could not save debug audio to %s", audio_path)

    def _request_response(self, wav_audio):
        audio_input = {
            "type": "audio",
            "data": base64.b64encode(wav_audio).decode("ascii"),
            "mime_type": "audio/wav",
        }
        request = {
            "model": CONF_CHAT_MODEL,
            "input": [
                {"type": "text", "text": "Listen to the user's speech and respond to their request."},
                audio_input,
            ],
            "system_instruction": GEMINI_SYSTEM_PROMPT,
            "tools": GEMINI_TOOLS,
        }
        if self.interaction_id:
            request["previous_interaction_id"] = self.interaction_id
        interaction = self.client.interactions.create(**request)

        should_sleep = False
        for _ in range(MAX_TOOL_ROUNDS):
            calls = [step for step in interaction.steps if step.type == "function_call"]
            if not calls:
                break
            results = []
            for call in calls:
                if call.name == "turn_on_the_lights":
                    result = turn_on_light()
                elif call.name == "turn_off_the_lights":
                    result = turn_off_light()
                elif call.name == "good_bye":
                    should_sleep = True
                    result = {"success": True, "status": "wake-word standby"}
                else:
                    result = {"error": f"Unknown function: {call.name}"}
                results.append(
                    {
                        "type": "function_result",
                        "name": call.name,
                        "call_id": call.id,
                        "result": [{"type": "text", "text": json.dumps(result)}],
                    }
                )
            interaction = self.client.interactions.create(
                model=CONF_CHAT_MODEL,
                input=results,
                system_instruction=GEMINI_SYSTEM_PROMPT,
                tools=GEMINI_TOOLS,
                previous_interaction_id=interaction.id,
            )

        self.interaction_id = interaction.id
        return interaction.output_text or "", should_sleep

    @staticmethod
    def _pcm_to_wav(pcm, sample_rate):
        import io

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm)
        return buffer.getvalue()

    @staticmethod
    def _make_wake_confirmation_sound():
        """Create a short confirmation beep for playback over the WebRTC call."""
        sample_count = int(GEMINI_WEBRTC_SAMPLE_RATE * WAKE_CUE_DURATION_SECONDS)
        time = np.arange(sample_count, dtype=np.float32) / GEMINI_WEBRTC_SAMPLE_RATE
        envelope = np.ones(sample_count, dtype=np.float32)
        fade_samples = min(int(GEMINI_WEBRTC_SAMPLE_RATE * 0.008), sample_count // 2)
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        envelope[:fade_samples] = fade
        envelope[-fade_samples:] = fade[::-1]
        tone = 0.18 * 32767 * envelope * np.sin(
            2 * np.pi * WAKE_CUE_FREQUENCY * time
        )
        return tone.astype("<i2").tobytes()

    @staticmethod
    def _make_processing_sound():
        """Create a two-tone cue confirming speech capture has ended."""
        sample_rate = GEMINI_WEBRTC_SAMPLE_RATE
        tone_samples = int(sample_rate * PROCESSING_CUE_TONE_SECONDS)
        fade_samples = min(int(sample_rate * 0.008), tone_samples // 2)
        envelope = np.ones(tone_samples, dtype=np.float32)
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        envelope[:fade_samples] = fade
        envelope[-fade_samples:] = fade[::-1]
        time = np.arange(tone_samples, dtype=np.float32) / sample_rate
        tones = [
            (0.18 * 32767 * envelope * np.sin(2 * np.pi * frequency * time))
            .astype("<i2")
            .tobytes()
            for frequency in PROCESSING_CUE_FREQUENCIES
        ]
        silence = np.zeros(
            int(sample_rate * PROCESSING_CUE_GAP_SECONDS), dtype="<i2"
        ).tobytes()
        return silence.join(tones)

    @staticmethod
    def _synthesize_speech(text):
        """Prefer the local Piper voice, then fall back to pyttsx3 and gTTS."""
        output_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
                output_path = output.name
            from piper import PiperVoice

            global _PIPER_VOICE
            if _PIPER_VOICE is None:
                with _PIPER_VOICE_LOCK:
                    if _PIPER_VOICE is None:
                        voice_path = Path(os.getenv(
                            "PIPER_VOICE_PATH",
                            str(Path.home() / ".local/share/piper/voices/en_US-lessac-medium.onnx"),
                        ))
                        if not voice_path.is_file():
                            raise FileNotFoundError(f"Piper voice model not found: {voice_path}")
                        _PIPER_VOICE = PiperVoice.load(voice_path)
            with wave.open(output_path, "wb") as wav_file:
                _PIPER_VOICE.synthesize_wav(text, wav_file)
        except Exception as piper_error:
            LOGGER.warning("Piper TTS unavailable (%s); falling back to pyttsx3", piper_error)
            try:
                import pyttsx3

                engine = pyttsx3.init()
                try:
                    engine.setProperty("rate", 180)
                    engine.save_to_file(text, output_path)
                    engine.runAndWait()
                finally:
                    engine.stop()
            except Exception as local_tts_error:
                LOGGER.warning("Local pyttsx3 unavailable (%s); using gTTS fallback", local_tts_error)
                from gtts import gTTS

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as output:
                    output_path = output.name
                gTTS(text=text, lang="en").save(output_path)

        try:
            pcm_frames = []
            with av.open(output_path) as container:
                resampler = AudioResampler(
                    format="s16", layout="mono", rate=GEMINI_WEBRTC_SAMPLE_RATE
                )
                for decoded in container.decode(audio=0):
                    for converted in resampler.resample(decoded):
                        pcm_frames.append(converted.to_ndarray().astype(np.int16).tobytes())
                for converted in resampler.resample(None):
                    pcm_frames.append(converted.to_ndarray().astype(np.int16).tobytes())
            return b"".join(pcm_frames)
        finally:
            if output_path and os.path.exists(output_path):
                os.unlink(output_path)
