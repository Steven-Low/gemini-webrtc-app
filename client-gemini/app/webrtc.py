# app/webrtc.py
import logging
import asyncio
import time
import numpy as np
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription, RTCIceCandidate, AudioStreamTrack
from aiortc.contrib.media import MediaStreamError
from av.audio.frame import AudioFrame
from config import CHUNK_DURATION_MS, ICE_SERVERS, WEBRTC_SAMPLE_RATE, SAMPLES_PER_FRAME, WEBRTC_TIME_BASE

LOGGER = logging.getLogger(__name__)

class GeminiOutputTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, audio_queue):
        super().__init__()
        self.audio_queue = audio_queue
        self.samplerate = WEBRTC_SAMPLE_RATE
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

class WebRTCManager:
    def __init__(self, gemini_audio_queue):
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**s) for s in ICE_SERVERS]))
        self.gemini_output_track = GeminiOutputTrack(gemini_audio_queue)
        
        # Callbacks to be set by the Application class
        self.on_ice_candidate_callback = None
        self.on_offer_created_callback = None
        self.on_answer_created_callback = None
        self.on_remote_track_callback = None
        self.on_remote_video_track_callback = None
        self.on_connection_closed_callback = None

        self._setup_event_handlers()
        
    def _setup_event_handlers(self):
        @self.pc.on("icecandidate")
        async def on_ice_candidate(candidate):
            if candidate and self.on_ice_candidate_callback:
                await self.on_ice_candidate_callback(candidate)

        @self.pc.on("track")
        async def on_track(track): 
            if track.kind == "audio": 
                if self.on_remote_track_callback:
                    await self.on_remote_track_callback(track)
            elif track.kind == "video":
                if self.on_remote_video_track_callback:
                    await self.on_remote_video_track_callback(track)
     
        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            LOGGER.debug(f"RTC Connection State: {self.pc.connectionState}")
            if self.pc.connectionState in ["failed", "disconnected", "closed"]:
                if self.on_connection_closed_callback:
                    await self.on_connection_closed_callback()

    async def create_offer(self):
        self.pc.addTrack(self.gemini_output_track)
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        if self.on_offer_created_callback:
            await self.on_offer_created_callback(self.pc.localDescription)

    async def handle_remote_offer(self, offer_sdp):
        self.pc.addTrack(self.gemini_output_track)
        await self.pc.setRemoteDescription(RTCSessionDescription(**offer_sdp))
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        if self.on_answer_created_callback:
            await self.on_answer_created_callback(self.pc.localDescription)

    async def handle_remote_answer(self, answer_sdp):
        await self.pc.setRemoteDescription(RTCSessionDescription(**answer_sdp))

    async def add_ice_candidate(self, candidate_data):
        rtcMessage = candidate_data.get('rtcMessage')
        candidate = rtcMessage["candidate"].split()
        try:
            await self.pc.addIceCandidate(
                RTCIceCandidate(
                    foundation=candidate[0].split(":")[1],
                    component=int(candidate[1]),
                    protocol=candidate[2],
                    priority=int(candidate[3]),
                    ip=candidate[4],
                    port=int(candidate[5]),
                    type=candidate[7],
                    sdpMid=rtcMessage["sdpMid"],
                    sdpMLineIndex=rtcMessage["sdpMLineIndex"]
                )
            )
            LOGGER.debug("Added remote ICE candidate.")
        except Exception as e:
            LOGGER.error(f"Error adding ICE candidate: {e}")


    async def close(self):
        if self.pc and self.pc.connectionState != "closed":
            await self.pc.close()