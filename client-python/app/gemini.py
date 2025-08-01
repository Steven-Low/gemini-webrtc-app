# app/gemini.py
import asyncio
import os
import sys
from google import genai
from google.genai import types
from aiortc.contrib.media import MediaStreamError
from av.audio.resampler import AudioResampler

from config import (
    GEMINI_SAMPLE_RATE, CONF_CHAT_MODEL, API_VERSION, CONFIG_RESPONSE,
    WEBRTC_SAMPLE_RATE, BYTES_PER_SAMPLE, CHUNK_SIZE_BYTES, CHUNK_DURATION_MS
)
 
class GeminiSessionManager:
    def __init__(self):
        self.session = None
        self.tasks = []
        self.audio_playback_queue = asyncio.Queue()

    async def start_session(self, webrtc_track):
        print("Initializing Gemini Live API session...")
        try:
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"), http_options={"api_version": API_VERSION})
            async with client.aio.live.connect(model=CONF_CHAT_MODEL, config=CONFIG_RESPONSE) as session:
                self.session = session
                print("Gemini LiveAPI connection established.")
                
                send_task = asyncio.create_task(self._send_to_gemini_task(webrtc_track))
                receive_task = asyncio.create_task(self._receive_from_gemini_task())
                
                self.tasks = [send_task, receive_task]
                await asyncio.gather(*self.tasks, return_exceptions=True)
        except Exception as e:
            print(f"Error during Gemini session lifecycle: {e}")
        finally:
            print("Gemini session has ended.")
            await self.stop_session()

    async def stop_session(self):
        if self.tasks:
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks = []
        
        while not self.audio_playback_queue.empty():
            self.audio_playback_queue.get_nowait()
        print("Gemini session cleaned up.")

    async def _play_audio(self, full_audio_buffer: bytes):
        for i in range(0, len(full_audio_buffer), CHUNK_SIZE_BYTES):
            chunk = full_audio_buffer[i:i + CHUNK_SIZE_BYTES]
            if not chunk:
                continue
            await self.audio_playback_queue.put(chunk)
            await asyncio.sleep(CHUNK_DURATION_MS / 1000)

    async def _receive_from_gemini_task(self):
        try:
            while True:
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        await self._play_audio(bytes(data))
                    elif text := response.text:
                        sys.stdout.write(f"\rGemini: {text}\n> ")
                        sys.stdout.flush()
        except asyncio.CancelledError:
            print("Receive_from_gemini_task cancelled.")
        except Exception as e:
            print(f"Error in receive_from_gemini_task: {e}")

    async def _send_to_gemini_task(self, track):
        resampler = AudioResampler(format="s16", layout="mono", rate=GEMINI_SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                resampled_frames = resampler.resample(frame)
                for r_frame in resampled_frames:
                    audio_bytes = r_frame.to_ndarray().tobytes()
                    await self.session.send(input={"data": audio_bytes, "mime_type": "audio/pcm"})
        except MediaStreamError:
            print("User audio track ended.")
        except asyncio.CancelledError:
            print("Send_to_gemini_task cancelled.")
        except Exception as e:
            print(f"Error in send_to_gemini_task: {e}")