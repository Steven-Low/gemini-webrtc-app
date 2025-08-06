# config.py
import fractions

# --- Signaling Server ---
SIGNALING_SERVER_URL = "http://10.10.10.124:3500"

# --- Gemini API ---
GEMINI_SAMPLE_RATE = 16000
CONF_CHAT_MODEL = "gemini-live-2.5-flash-preview"  # "gemini-live-2.5-flash-preview" | gemini-2.0-flash-live-001
GEMINI_API_VERSION = "v1alpha" #"v1beta"
GEMINI_VOICE = "Puck" # Orus | Kore | Puck | Charon | Fenrir | Aoede | Leda | Zephyr
GEMINI_LANGUAGE = "en-US" # en-US | en-UK | ko-KR | ta-IN | ja-JP | fr-FR


# --- WebRTC Audio ---
WEBRTC_SAMPLE_RATE = 24000
WEBRTC_TIME_BASE = fractions.Fraction(1, WEBRTC_SAMPLE_RATE)
SAMPLES_PER_FRAME = int(WEBRTC_SAMPLE_RATE * 0.02) # 20ms frame
BYTES_PER_SAMPLE = 2
CHUNK_DURATION_MS = 20
CHUNK_SIZE_BYTES = int((WEBRTC_SAMPLE_RATE * (CHUNK_DURATION_MS / 1000)) * BYTES_PER_SAMPLE)

# --- STUN Servers ---
ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:stun1.l.google.com:19302"},
    {"urls": "stun:stun2.l.google.com:19302"},
]