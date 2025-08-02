# app/application.py
import asyncio
import random
from .signaling import SignalingClient
from .webrtc import WebRTCManager
from .gemini import GeminiSessionManager
from .cli import CLIHandler

class Application:
    def __init__(self):
        self.caller_id = f"666666"
        self.remote_user_id = None
        
        self.gemini_manager = GeminiSessionManager()
        self.webrtc_manager = WebRTCManager(self.gemini_manager.audio_playback_queue)
        self.signaling_client = SignalingClient()
        self.cli = CLIHandler(self)
        
        self._wire_components()

    def _wire_components(self):
        # Signaling -> App
        self.signaling_client.on_connect_callback = lambda: print(f"Connected to signaling with ID: {self.caller_id}")
        self.signaling_client.on_new_call_callback = self.handle_incoming_call
        self.signaling_client.on_call_answered_callback = self.webrtc_manager.handle_remote_answer
        self.signaling_client.on_ice_candidate_callback = self.webrtc_manager.add_ice_candidate

        # WebRTC -> App 
        self.webrtc_manager.on_offer_created_callback = self._handle_offer_created
        self.webrtc_manager.on_answer_created_callback = self._handle_answer_created
        self.webrtc_manager.on_ice_candidate_callback = self._handle_ice_candidate
        self.webrtc_manager.on_remote_track_callback = self.gemini_manager.start_session
        self.webrtc_manager.on_connection_closed_callback = self.hang_up
        
    # --- Signalling Handler Methods ---
    async def handle_incoming_call(self, data):
        caller_id = data.get('callerId')
        rtc_message = data.get('rtcMessage')
        print(f"Incoming call from {caller_id}. Auto-answering.")
        self.remote_user_id = caller_id
        await self.webrtc_manager.handle_remote_offer(rtc_message)
    # ---------------------------------- 

    # -- Webrtc Handler Methods ---
    async def _handle_offer_created(self, sdp):
        if self.remote_user_id:
            await self.signaling_client.send_offer(self.remote_user_id, sdp)

    async def _handle_answer_created(self, sdp):
        if self.remote_user_id:
            await self.signaling_client.send_answer(self.remote_user_id, sdp)
            
    async def _handle_ice_candidate(self, candidate):
        if self.remote_user_id:
            await self.signaling_client.send_ice_candidate(self.remote_user_id, candidate)
    # -----------------------------

    async def start_call(self, target_id):
        if not target_id:
            print("Target ID cannot be empty.")
            return
        print(f"Starting call to {target_id}...")
        self.remote_user_id = target_id
        await self.webrtc_manager.create_offer()
        
    async def hang_up(self):
        print("Hanging up call...")
        await self.gemini_manager.stop_session()
        await self.webrtc_manager.close()
        # Reset state
        self.gemini_manager = GeminiSessionManager()
        self.webrtc_manager = WebRTCManager(self.gemini_manager.audio_playback_queue)
        self._wire_components()
        self.remote_user_id = None
        await self.cli.show_menu()

    async def shutdown(self):
        print("Shutting down application...")
        # Check if hang_up needs to be awaited if it's async
        if asyncio.iscoroutinefunction(self.hang_up):
            await self.hang_up()
        else:
            self.hang_up()
        await self.signaling_client.disconnect()

    async def run(self):
        try:
            await self.signaling_client.connect(self.caller_id)
            await self.cli.loop()
        except Exception as e:
            print(f"An error occurred in the application: {e}")
        finally:
            await self.shutdown()
