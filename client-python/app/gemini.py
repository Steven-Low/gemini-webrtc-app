# app/gemini.py
import asyncio
import os
import sys
from google import genai
from google.genai import types
from aiortc.contrib.media import MediaStreamError
from av.audio.resampler import AudioResampler

from config import (
    GEMINI_SAMPLE_RATE, 
    CONF_CHAT_MODEL, 
    WEBRTC_SAMPLE_RATE, 
    BYTES_PER_SAMPLE, 
    CHUNK_SIZE_BYTES,
    CHUNK_DURATION_MS,
    GEMINI_API_VERSION, 
    GEMINI_VOICE,
    GEMINI_LANGUAGE
)

GEMINI_TOOLS = [
    {'google_search': {}}, 
    {"code_execution": {}},

]
GEMINI_SYSTEM_PROMPT = """
You are a helpful and knowledgeable assistant. You have access to the google_search tool to look up information. 
However, you must not use this tool automatically. Before performing any search, always ask the user for permission or wait for explicit instructions.
Only proceed with the search if the user clearly tells you to do so. Answer in short and concise sentence.
"""
 
class GeminiSessionManager:
    def __init__(self):
        self.session = None
        self.tasks = []
        self.audio_playback_queue = asyncio.Queue(maxsize=10)
        self.session_handle = None
        self.failed = False

    #TODO: Handle video frames
    async def start_video_processing(self, webrtc_track): 
        asyncio.create_task(self._drain_track(webrtc_track))

    async def _drain_track(self, track):
        print("Skipping webrtc video tracks...")
        try:
            while True:
                await track.recv()  
        except MediaStreamError:
            print(f"Track {track.kind}:{track.id} ended.")
        except asyncio.CancelledError:
            pass 

    async def start_session(self, webrtc_track):
        print("Initializing Gemini Live API session...")
        
        try: 
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"), http_options={"api_version": GEMINI_API_VERSION})
            while True:
                gemini_config = types.LiveConnectConfig(
                    response_modalities=['AUDIO'],
                    context_window_compression=(
                        types.ContextWindowCompressionConfig(
                            sliding_window=types.SlidingWindow(),
                        )
                    ),
                    session_resumption=types.SessionResumptionConfig(
                        handle=self.session_handle
                    ),
                    speech_config={
                        "voice_config": {"prebuilt_voice_config": {"voice_name": GEMINI_VOICE}},
                        "language_code": GEMINI_LANGUAGE
                    },
                    tools=GEMINI_TOOLS,
                    system_instruction=GEMINI_SYSTEM_PROMPT
                )   
                
                if self.session_handle:
                    print(f"Attempting to resume session with handle: {self.session_handle}")

                try:
                    async with client.aio.live.connect(model=CONF_CHAT_MODEL, config=gemini_config) as session:
                        self.session = session
                        print("Gemini LiveAPI connection established.")
                        
                        send_task = asyncio.create_task(self._send_to_gemini_task(webrtc_track))
                        receive_task = asyncio.create_task(self._receive_from_gemini_task())
                        
                        self.tasks = [send_task, receive_task]
                        self.failed = False
                        await asyncio.gather(*self.tasks)
                         
                except Exception as e:
                    print(f"Session Timeout with error: {e}")
                    await self.stop_session()
                    
                finally:
                    if not self.failed:
                        print(f"Gemini session has ended cleanly: Failed {self.failed}")
                        break 

        except Exception as e:
            print(f"Gemini session has ended unexpectedly: {e}")
        
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

        if self.session:
            await self.session.close()
            self.session = None

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
                    elif go_away := response.go_away:
                        print("Gemini session timeout:",go_away.time_left)
                        raise TimeoutError(f"Gemini session timeout: {go_away.time_left}")
                    
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        print(f"Update Resumable: {update.resumable} Update Handle: {update.new_handle}")
                        if update.resumable and update.new_handle:
                            self.session_handle = update.new_handle
                            print("return update new handle")

                    # The model might generate and execute Python code to use Search
                    if response.server_content:
                        if model_turn := response.server_content.model_turn:
                            for part in model_turn.parts:
                                if part.executable_code:
                                    print("Code:", part.executable_code.code)
                                elif part.code_execution_result:
                                    print("Output:", part.code_execution_result.output)

                    if response.server_content and response.server_content.turn_complete:
                        break
                        
        except asyncio.CancelledError:
            print("Receive_from_gemini_task cancelled.")
        except Exception as e:
            print(f"Error in receive_from_gemini_task: {e}")
            self.failed = True
            raise

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
            self.failed = True
            raise

