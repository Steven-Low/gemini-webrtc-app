from app.llm.gemini import GeminiClientManager
from app.models.gemini_track import GeminiOutputTrack
from app.core.call_session import CallSession

LLM_MANAGERS = {
    "gemini": GeminiClientManager,
}

OUTPUT_TRACK_FACTORIES = {
    "gemini": GeminiOutputTrack,
}

def create_call_session(remote_user_id, signaling_client, on_cleanup_callback, llm_name="gemini"):
    manager_cls = LLM_MANAGERS.get(llm_name, GeminiClientManager)
    track_cls = OUTPUT_TRACK_FACTORIES.get(llm_name, GeminiOutputTrack)
    return CallSession(remote_user_id, signaling_client, manager_cls, track_cls, on_cleanup_callback)
