# app/llm/base.py
from abc import ABC, abstractmethod
import asyncio

class BaseLLMManager(ABC):
    def __init__(self):
        # All LLMs must expose a playback queue
        self.audio_playback_queue = asyncio.Queue()

    @abstractmethod
    async def start_session(self, webrtc_track):
        pass

    @abstractmethod
    async def stop_session(self):
        pass

    async def start_video_processing(self, webrtc_track):
        """Optional: override if your LLM cares about video"""
        pass
