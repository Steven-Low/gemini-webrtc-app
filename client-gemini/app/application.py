import asyncio
import logging
from .signaling import SignalingClient
from .call_session import CallSession  
from .cli import CLIHandler
from config import MAX_SESSIONS

LOGGER = logging.getLogger(__name__)

class Application:
    def __init__(self):
        self.main_caller_id = "666666" # The public "reception" ID
        self.active_sessions = {}      # Store active call session via remote user id key
        self.signaling_client = SignalingClient()
        self.cli = CLIHandler(self)   
        self._wire_signaling()

    def _wire_signaling(self):
        """Wires up the signaling client to the application's handlers."""
        self.signaling_client.on_connect_callback = lambda: LOGGER.info(f"Connected to signaling. My main ID is: {self.main_caller_id}")
        self.signaling_client.on_new_call_callback = self.handle_incoming_call
        self.signaling_client.on_call_answered_callback = self.handle_call_answered
        self.signaling_client.on_ice_candidate_callback = self.handle_ice_candidate
        self.signaling_client.on_call_ended_callback = self.handle_call_ended

    # --- Signaling Handler Methods ---
    async def handle_incoming_call(self, data):
        caller_id = data.get('callerId')
        rtc_message = data.get('rtcMessage')

        LOGGER.info(f"Incoming call from {caller_id} to main ID.")

        if len(self.active_sessions) >= MAX_SESSIONS:
            LOGGER.warning(f"At max capacity ({MAX_SESSIONS} calls). Rejecting call from {caller_id}.")
            return

        session = CallSession(
            remote_user_id=caller_id,
            signaling_client=self.signaling_client,
            on_cleanup_callback=self.remove_session
        )
        self.active_sessions[caller_id] = session
        await session.webrtc_manager.handle_remote_offer(rtc_message)

    async def handle_call_answered(self, data):
        callee_id = data.get('callee')
        session = self.active_sessions.get(callee_id)
        if session:
            await session.webrtc_manager.handle_remote_answer(data.get('rtcMessage'))

    async def handle_call_ended(self, data):
        caller_id = data.get("senderId")
        LOGGER.warning(f"Caller {caller_id} hung up before call connected.")
        session = self.active_sessions.get(caller_id)
        if session:
            await session.cleanup() 

    async def handle_ice_candidate(self, data):
        # Find the correct session and delegate the ICE candidate
        sender_id = data.get('sender')
        session = self.active_sessions.get(sender_id)
        if session:
            await session.webrtc_manager.add_ice_candidate(data)
    # ----------------------------------

    async def remove_session(self, session_id):
        """Callback function to remove a session when it has finished cleaning up."""
        LOGGER.info(f"Removing session {session_id} from active list.")
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
        LOGGER.info(f"Current active sessions: {len(self.active_sessions)}")

    async def start_call(self, target_id):
        """Initiates an outbound call to a target user."""
        LOGGER.info(f"Attempting to start call to {target_id}.")

        if target_id in self.active_sessions:
            LOGGER.warning(f"Already in an active session with {target_id}. Cannot start a new call.")
            return

        if len(self.active_sessions) >= MAX_SESSIONS:
            LOGGER.warning(f"At max capacity ({MAX_SESSIONS} calls). Cannot start a new call.")
            return

        LOGGER.info(f"Creating new session for outbound call to {target_id}.")
        session = CallSession(
            remote_user_id=target_id,
            signaling_client=self.signaling_client,
            on_cleanup_callback=self.remove_session
        )
        self.active_sessions[target_id] = session
        
        try:
            await session.initiate_call()
            LOGGER.info(f"Offer sent to {target_id}. Waiting for them to answer.")
        except Exception as e:
            LOGGER.error(f"Failed to initiate call to {target_id}. Error: {e}")
            await session.cleanup()

    async def hang_up(self, session_id_to_hang_up):
        """Hangs up a specific call by its ID."""
        LOGGER.info(f"Attempting to hang up session {session_id_to_hang_up}.")
        session = self.active_sessions.get(session_id_to_hang_up)
        if session:
            # This will trigger the session's internal cleanup, which will then call remove_session
            await session.cleanup()
        else:
            LOGGER.warning(f"No active session found with ID {session_id_to_hang_up}.")

    async def shutdown(self):
        LOGGER.warning("Shutting down application...")
        # Create a copy of the sessions to iterate over, as cleanup will modify the dict
        all_sessions = list(self.active_sessions.values())
        for session in all_sessions:
            await session.cleanup()
        await self.signaling_client.disconnect()

    async def run(self):
        try:
            # Connect to signaling using the main "reception" ID
            await self.signaling_client.connect(self.main_caller_id)
            await self.cli.loop() # Assuming the CLI now calls hang_up with a specific ID
        except Exception as e:
            LOGGER.error(f"An error occurred in the application: {e}")
        finally:
            await self.shutdown()