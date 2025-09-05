# app/signaling.py
import asyncio
import socketio
from config import SIGNALING_SERVER_URL

class SignalingClient:
    def __init__(self):
        self.sio = socketio.AsyncClient()
        self.caller_id = ""
        
        # Callbacks
        self.on_connect_callback = None
        self.on_new_call_callback = None
        self.on_call_answered_callback = None
        self.on_ice_candidate_callback = None
        self.on_call_ended_callback = None

        self._setup_event_handlers()

    def _setup_event_handlers(self):
        @self.sio.event
        async def connect():
            if self.on_connect_callback:
                self.on_connect_callback()

        @self.sio.event
        async def newCall(data):
            if self.on_new_call_callback:
                await self.on_new_call_callback(data)

        @self.sio.event
        async def callAnswered(data):
            if self.on_call_answered_callback:
                await self.on_call_answered_callback(data)

        @self.sio.event
        async def ICEcandidate(data):
            if self.on_ice_candidate_callback:
                await self.on_ice_candidate_callback(data)
        
        @self.sio.event
        async def callEnded(data):
            if self.on_call_ended_callback:
                await self.on_call_ended_callback(data)
        
                
    async def connect(self, caller_id):
        self.caller_id = caller_id
        await self.sio.connect(f"{SIGNALING_SERVER_URL}?callerId={self.caller_id}", transports=["websocket"])

    async def disconnect(self):
        if self.sio.connected:
            await self.sio.disconnect()
            
    async def send_offer(self, callee_id, sdp):
        await self.sio.emit('call', {'calleeId': callee_id, 'rtcMessage': {'type': sdp.type, 'sdp': sdp.sdp}})

    async def send_answer(self, caller_id, sdp):
        await self.sio.emit('answerCall', {'callerId': caller_id, 'rtcMessage': {'type': sdp.type, 'sdp': sdp.sdp}})
        
    async def send_ice_candidate(self, callee_id, candidate):
        await self.sio.emit('ICEcandidate', {'calleeId': callee_id, 'rtcMessage': {'label': candidate.sdpMLineIndex, 'id': candidate.sdpMid, 'candidate': candidate.candidate}})

    # async def send_hangup(self, target_id):
    #     await self.sio.emit('hangupCall', {'targetId': target_id})