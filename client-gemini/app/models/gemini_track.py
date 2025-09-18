# app/webrtc.py
import asyncio
import time
import numpy as np
from aiortc import ( 
    AudioStreamTrack
)
from aiortc.contrib.media import MediaStreamError
from av.audio.frame import AudioFrame
from app.config.constants import (
    GEMINI_WEBRTC_SAMPLE_RATE, 
    SAMPLES_PER_FRAME, 
    WEBRTC_TIME_BASE
)

class GeminiOutputTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, audio_queue):
        super().__init__()
        self.audio_queue = audio_queue
        self.samplerate = GEMINI_WEBRTC_SAMPLE_RATE
        self.samples_per_frame = SAMPLES_PER_FRAME
        self._start_time = time.time()
        self._timestamp = 0

    async def recv(self):
        wait_until = self._start_time + (self._timestamp + self.samples_per_frame) / self.samplerate
        await asyncio.sleep(max(0, wait_until - time.time()))
        try:
            data_bytes = await self.audio_queue.get()
            frame = AudioFrame.from_ndarray(
                np.frombuffer(data_bytes, dtype=np.int16).reshape(1, -1),
                format='s16', layout='mono'
            )
            frame.pts = self._timestamp
            frame.sample_rate = self.samplerate
            frame.time_base = WEBRTC_TIME_BASE
            self._timestamp += frame.samples
            self.audio_queue.task_done()
            return frame
        except asyncio.CancelledError:
            raise MediaStreamError