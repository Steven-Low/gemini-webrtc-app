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
    BYTES_PER_SAMPLE, 
    CHUNK_SIZE_BYTES,
    CHUNK_DURATION_MS,
    GEMINI_API_VERSION, 
    GEMINI_VOICE,
    GEMINI_LANGUAGE
)

from .homeassistant_api import turn_on_light, turn_off_light
turn_on_the_lights = {'name': 'turn_on_the_lights'}
turn_off_the_lights = {'name': 'turn_off_the_lights'}

GEMINI_TOOLS = [
    {'google_search': {}}, 
    {"code_execution": {}},
    {"function_declarations": [turn_on_the_lights, turn_off_the_lights]}
]
GEMINI_SYSTEM_PROMPT = """
I. Core Elements
Task Definition:
You are a helpful and informative AI assistant with several capabilities:
Answering factual questions using your knowledge base (cut-off date: 2023-04) and supplementing information with web search results.
Retrieving information from the web using the 'google_search'  tool.
Safety & Ethics
Absolute Priority: Responses must never be harmful, incite violence, promote hatred, or violate ethical standards. Err on the side of caution if safety is in question.
Browser: Cite reputable sources and prioritize trustworthy websites.
Controversial Topics: Provide objective information without downplaying harmful content or implying false equivalency of perspectives.
Social Responsibility: Do not generate discriminatory responses, promote hate speech, or are socially harmful.
Knowledge Boundaries:
Limit factual answers to knowledge acquired before 2023-04.
Direct users to the 'google_search'  tool for topics outside your knowledge base or those requiring real-time information.
Source Transparency: Distinguish between existing knowledge and information found in search results. Prioritize reputable and trustworthy websites when citing search results.
II. Refinement Elements
Personality & Style:
Maintain a polite and informative tone. Inject light humor only when it feels natural and doesn’t interfere with providing accurate information.
Self Awareness
Identify yourself as an AI language model.
Acknowledge when you lack information and suggest using the 'google_search'  tool.
Refer users to human experts for complex inquiries outside your scope.
Handling Disagreement: While prioritizing the user’s request, consider providing an alternate perspective if it aligns with safety and objectivity and acknowledges potential biases.
IV. Google Search Integration
Focused Answers: When answering questions using google search tool results, synthesize information from the provided results.
Source Prioritization: Prioritize reputable and trustworthy websites. Cite sources using numerical references [1]. Avoid generating URLs within the response.
Knowledge Integration: You may supplement web results with your existing knowledge base, clearly identifying the source of each piece of information.
Conflict Resolution: If search results present conflicting information, acknowledge the discrepancy and summarize the different viewpoints found [1,2].
Iterative Search: Conduct multiple searches (up to [Number]) per turn, refining your queries based on user feedback.
"""
 
class GeminiSessionManager:
    def __init__(self, remote_user_id):
        self.session = None
        self.remote_user_id = remote_user_id
        self.tasks = []
        self.audio_playback_queue = asyncio.Queue(maxsize=10)
        self.raw_audio_to_play_queue = asyncio.Queue(maxsize=200) # increase to prevent interrupt block
        self.session_handle = None
        self.failed = False

        self.interrupt_enabled = True

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
                        playback_task = asyncio.create_task(self._playback_manager_task())

                        self.tasks = [send_task, receive_task, playback_task]
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

    async def _playback_manager_task(self):
        """
        A dedicated, permanent task that pulls raw audio buffers from a queue
        and then calls the "slow" chunking function. This decouples playback
        from the main receive loop.
        """
        print("Playback manager started.")
        try:
            while True:
                raw_buffer = await self.raw_audio_to_play_queue.get()
                await self._play_audio(raw_buffer)
                self.raw_audio_to_play_queue.task_done()
        except asyncio.CancelledError:
            print("Playback manager cancelled.")

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
                        print(f"[Audio Bytes] [{self.remote_user_id}] {len(data)}")
                        await self.raw_audio_to_play_queue.put(bytes(data))
                    elif text := response.text:
                        sys.stdout.write(f"\rGemini: {text}\n> ")
                        sys.stdout.flush()
                    elif go_away := response.go_away:
                        print("Gemini session timeout:",go_away.time_left)
                        raise TimeoutError(f"Gemini session timeout: {go_away.time_left}")
                    
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        # print(f"Update Resumable: {update.resumable} Update Handle: {update.new_handle}")
                        if update.resumable and update.new_handle:
                            self.session_handle = update.new_handle

                    # The model might generate and execute Python code to use Search
                    if response.server_content:
                        if model_turn := response.server_content.model_turn:
                            for part in model_turn.parts:
                                if part.executable_code:
                                    print("Code:", part.executable_code.code)
                                elif part.code_execution_result:
                                    print("Output:", part.code_execution_result.output)
                                        
                        if response.server_content.interrupted is self.interrupt_enabled:
                            print("Interupting... Clearing audio queues.")
                            while not self.raw_audio_to_play_queue.empty():
                                self.raw_audio_to_play_queue.get_nowait()
                            while not self.audio_playback_queue.empty():
                                self.audio_playback_queue.get_nowait()
                                    
                    elif response.tool_call:
                        function_responses = []
                        for fc in response.tool_call.function_calls:

                            if fc.name == "turn_on_the_lights":
                                result = turn_on_light()
                            elif fc.name == "turn_off_the_lights":
                                result = turn_off_light()
                            else:
                                result = {"error": f"Unknown function: {fc.name}"}

                            function_response = types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response={ "result": result}  
                            )
                            function_responses.append(function_response)

                        await self.session.send_tool_response(function_responses=function_responses)

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

