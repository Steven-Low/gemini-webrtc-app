from .webrtc import WebRTCManager
from .gemini import GeminiSessionManager

class CallSession:
    """
    Represents a single, self-contained call session.
    It manages its own WebRTC and Gemini instances.
    """
    def __init__(self, remote_user_id, signaling_client, on_cleanup_callback):
        print(f"SESSION [{remote_user_id}]: Creating new call session.")
        self.remote_user_id = remote_user_id
        self.signaling_client = signaling_client
        self.on_cleanup_callback = on_cleanup_callback # To notify the main app when this session ends

        # Each session gets its own, isolated managers.
        self.gemini_manager = GeminiSessionManager(self.remote_user_id)
        self.webrtc_manager = WebRTCManager(self.gemini_manager.audio_playback_queue)

        self.cleaned_up = False
        self._wire_components()

    def _wire_components(self):
        """Wires the internal components for this specific session."""
        # WebRTC -> Gemini
        self.webrtc_manager.on_remote_track_callback = self.gemini_manager.start_session
        self.webrtc_manager.on_remote_video_track_callback = self.gemini_manager.start_video_processing
        
        # WebRTC -> Signaling (via this session)
        self.webrtc_manager.on_offer_created_callback = self._handle_offer_created
        self.webrtc_manager.on_answer_created_callback = self._handle_answer_created
        self.webrtc_manager.on_ice_candidate_callback = self._handle_ice_candidate
        
        # WebRTC -> Cleanup
        self.webrtc_manager.on_connection_closed_callback = self.cleanup

    # --- Methods to forward WebRTC events to the Signaling Client ---
    async def _handle_offer_created(self, sdp):
        await self.signaling_client.send_offer(self.remote_user_id, sdp)

    async def _handle_answer_created(self, sdp):
        await self.signaling_client.send_answer(self.remote_user_id, sdp)
            
    async def _handle_ice_candidate(self, candidate):
        await self.signaling_client.send_ice_candidate(self.remote_user_id, candidate)

    async def initiate_call(self):
        print(f"SESSION [{self.remote_user_id}]: Initiating outbound call...")
        await self.webrtc_manager.create_offer()

    async def cleanup(self):
        """Shuts down all resources for this session."""
        if getattr(self, "cleaned_up", False):
            print(f"SESSION [{self.remote_user_id}]: Cleanup already performed. Skipping.")
            return
        self.cleaned_up = True
        print(f"SESSION [{self.remote_user_id}]: Cleaning up...")
        await self.gemini_manager.stop_session()
        await self.webrtc_manager.close()
        # Notify the main application that this session is now over.
        if self.on_cleanup_callback:
            await self.on_cleanup_callback(self.remote_user_id)