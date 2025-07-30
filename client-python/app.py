import asyncio
import socketio
import uuid
import sys
import os
import random

from aiortc import (
    MediaStreamTrack,
    RTCPeerConnection,
    RTCConfiguration,
    RTCIceServer,
    RTCSessionDescription,
    RTCIceCandidate,
    AudioStreamTrack
)
from aiortc.contrib.media import MediaPlayer, MediaRecorder
from aiortc.rtcrtpsender import RTCRtpSender
from aiortc.contrib.media import MediaStreamError
from google import genai
from dotenv import load_dotenv
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
import base64
import json
import time
import fractions
import numpy as np


load_dotenv()

# --- Global Variables for State ---
sio = socketio.AsyncClient()
pc = None  # RTCPeerConnection instance
local_player = None # MediaPlayer for local audio source
remote_audio_track = None

caller_id =  "666666" #f"{random.randint(0,999999):06}" # Generate a random 6-char ID
other_user_id = None
remote_rtc_message = None

# Media source for local stream (Audio Only)
# 'default:audio' attempts to use your default microphone.
# On Linux, you might need 'default:audio' or specific device names.
# On Windows, 'default:audio' usually works with 'dshow' format.
# If 'default:audio' doesn't work, you can try a test audio file like: 'test.wav'
# Ensure 'test.wav' exists in the same directory for the test file option.
MEDIA_SOURCE = "test.wav" #'default:audio'

# Media recorder for remote stream (optional, for saving remote audio)
recorder = None

# Flag for media control
local_mic_on = True


GEMINI_SAMPLE_RATE = 16000
CONF_CHAT_MODEL = "gemini-2.0-flash-live-001"  
API_VERSION = "v1beta"
CONFIG_RESPONSE = {"response_modalities": ["AUDIO"]}
WEBRTC_SAMPLE_RATE = 24000
WEBRTC_TIME_BASE = fractions.Fraction(1, WEBRTC_SAMPLE_RATE)
SAMPLES_PER_FRAME = int(WEBRTC_SAMPLE_RATE * 0.02) # 20ms frame
BYTES_PER_SAMPLE = 2
CHUNK_DURATION_MS = 20
CHUNK_SIZE_BYTES = int((WEBRTC_SAMPLE_RATE * (CHUNK_DURATION_MS / 1000)) * BYTES_PER_SAMPLE) # This will be 960 bytes

gemini_to_user_audio_queue = asyncio.Queue()
user_to_gemini_audio_queue = asyncio.Queue()
current_audio_buffer = bytearray()
gemini_session_tasks = []


# --- Utility Functions ---
def set_other_user_id(user_id):
    global other_user_id
    other_user_id = user_id
    print(f"Set other user ID to: {other_user_id}")

def set_remote_rtc_message(message):
    global remote_rtc_message
    remote_rtc_message = message

def send_ice_candidate(data):
    # This sends ICE candidate through the signaling server
    asyncio.create_task(sio.emit('ICEcandidate', data))
    print(f"[Signaling] Sending ICE candidate to {data.get('calleeId')}")

def send_call(data):
    # This sends the SDP offer through the signaling server
    asyncio.create_task(sio.emit('call', data))
    print(f"[Signaling] Sending call to {data.get('calleeId')}")

def answer_call(data):
    # This sends the SDP answer through the signaling server
    asyncio.create_task(sio.emit('answerCall', data))
    print(f"[Signaling] Sending answer to {data.get('callerId')}")

 
class GeminiOutputTrack(AudioStreamTrack):
    """
    An audio track that streams audio FROM Gemini TO the user.
    """
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.samplerate = WEBRTC_SAMPLE_RATE
        self.samples_per_frame = SAMPLES_PER_FRAME
        self._start_time = time.time()
        self._timestamp = 0

    async def recv(self):
        """
        Pulls audio data from the queue, wraps it in an AudioFrame, and returns it.
        This is called automatically by the WebRTC transport.
        """
        # Timestamping logic for smooth playback
        wait_until = self._start_time + (self._timestamp + self.samples_per_frame) / self.samplerate
        await asyncio.sleep(max(0, wait_until - time.time()))

        try:
            data_bytes = await gemini_to_user_audio_queue.get()

            data_s16 = np.frombuffer(data_bytes, dtype=np.int16)
            data_reshaped = data_s16.reshape(1, -1) # Reshape for PyAV mono

            frame = AudioFrame.from_ndarray(data_reshaped, format='s16', layout='mono')
            frame.pts = self._timestamp
            frame.sample_rate = self.samplerate
            frame.time_base = WEBRTC_TIME_BASE

            self._timestamp += frame.samples
            gemini_to_user_audio_queue.task_done()
            return frame
        except asyncio.CancelledError:
            raise MediaStreamError

async def cancel_gemini_tasks():
    global gemini_session_tasks
    if gemini_session_tasks:
        print("Cancelling Gemini tasks...")
        for task in gemini_session_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*gemini_session_tasks, return_exceptions=True)
        gemini_session_tasks = []
        # Clear the queue
        while not gemini_to_user_audio_queue.empty():
            gemini_to_user_audio_queue.get_nowait()

async def play_audio(full_audio_buffer: bytes):
    """
    Takes a large buffer of audio data, chops it into timed 20ms chunks,
    and puts them onto the queue for the GeminiOutputTrack to consume.
    """
    print(f"[PLAYBACK] Starting playback of {len(full_audio_buffer)} bytes ({len(full_audio_buffer) / (WEBRTC_SAMPLE_RATE * BYTES_PER_SAMPLE):.2f}s).")
    for i in range(0, len(full_audio_buffer), CHUNK_SIZE_BYTES):
        chunk = full_audio_buffer[i:i + CHUNK_SIZE_BYTES]
        if not chunk:
            continue
            
        await gemini_to_user_audio_queue.put(chunk)


async def receive_from_gemini_task(session):
    """
    Listens for responses from Gemini and puts audio data into the outgoing queue.
    """
    print("Task started: Receiving audio and text from Gemini.")
    try:
        while True:
            turn = session.receive()
            async for response in turn:
                if data := response.data:
                    current_audio_buffer.extend(data)
                if text := response.text:
                    sys.stdout.write(f"\rGemini: {text}\n> ")
                    sys.stdout.flush()
            await play_audio(bytes(current_audio_buffer))
            current_audio_buffer.clear()

    except asyncio.CancelledError:
        print("Receive_from_gemini_task cancelled.")
    except Exception as e:
        print(f"Error in receive_from_gemini_task: {e}")
   

async def send_to_gemini_task(session, track):
    """
    Receives audio from the user's track, resamples it, and sends it to Gemini.
    """
    print("Task started: Sending user audio to Gemini.")
    resampler = AudioResampler(format="s16", layout="mono", rate=GEMINI_SAMPLE_RATE)
    try:
        while True:
            frame = await track.recv()
            resampled_frames = resampler.resample(frame)
            for resampled_frame in resampled_frames:         
                audio = resampled_frame.to_ndarray().tobytes()
                b64_audio = base64.b64encode(audio).decode()   # ???
                msg = {"data": audio,"mime_type": "audio/pcm"}
                await session.send(input=msg) 
                 
    except MediaStreamError:
        print("User audio track ended.")
    except asyncio.CancelledError:
        print("Send_to_gemini_task cancelled.")
    except Exception as e:
        print(f"Error in send_to_gemini_task: {e}")

async def start_gemini_session_and_tasks(track):
    """
    Initializes the Gemini client and starts the concurrent send/receive tasks.
    """
    global gemini_session_tasks
    print("Initializing Gemini Live API session...")
    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"), http_options={"api_version": API_VERSION})
        async with client.aio.live.connect(model=CONF_CHAT_MODEL, config=CONFIG_RESPONSE) as session:
            print("Gemini LiveAPI connection established.")
            # Start the two main tasks concurrently
            send_task = asyncio.create_task(send_to_gemini_task(session, track))
            receive_task = asyncio.create_task(receive_from_gemini_task(session))
            gemini_session_tasks = [send_task, receive_task]
            await asyncio.gather(*gemini_session_tasks)

    except Exception as e:
        print(f"Error during Gemini session lifecycle: {e}")
    finally:
        print("Gemini session has ended.")
        await cancel_gemini_tasks()

# --- RTCPeerConnection Setup ---
async def create_peer_connection():
    global pc, local_player

    if pc:
        print("Closing existing peer connection.")
        await pc.close()

    pc = RTCPeerConnection(
        RTCConfiguration(
            iceServers=[
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun2.l.google.com:19302"])
            ]
        )
    )

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        print(f"RTC => PeerConnection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
        elif pc.connectionState == "disconnected" or pc.connectionState == "closed":
            print("PeerConnection disconnected or closed. Resetting.")
            await cleanup_webrtc()
            print("Please type 'menu' to go back to the main menu.")

    @pc.on("icecandidate")
    async def on_ice_candidate(candidate):
        if candidate:
            print(f"RTC => Generated ICE candidate: {candidate.candidate}")
            send_ice_candidate({
                'calleeId': other_user_id, # Target of the call
                'rtcMessage': {
                    'label': candidate.sdpMLineIndex,
                    'id': candidate.sdpMid,
                    'candidate': candidate.candidate,
                },
            })

    @pc.on("negotiationneeded")
    async def on_negotiation_needed():
        print("RTC => Negotiation needed: Creating offer")
        try:
            # Create an SDP offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            send_call({
                'calleeId': other_user_id,
                'rtcMessage': {
                    'type': pc.localDescription.type,
                    'sdp': pc.localDescription.sdp,
                },
            })
        except Exception as e:
            print(f"Error creating/sending offer: {e}")

    @pc.on("track")
    async def on_track(track):
        global remote_audio_track, recorder
        print(f"RTC => Track {track.kind} received from remote peer.")

        if track.kind == "audio":
            remote_audio_track = track
            print(f"Track type: {type(track)}")
            print(f"Track module: {track.__class__.__module__}")



            asyncio.create_task(start_gemini_session_and_tasks(track))

            # print("Remote audio track received. Saving to file...")
            # recorder = MediaRecorder(f"remote_audio_{other_user_id}.wav")  # Save to WAV file
            # recorder.addTrack(track)
            # await recorder.start()
            print(f"Recording remote audio to remote_audio_{other_user_id}.wav")

 
        else:
            print(f"Ignoring non-audio track of kind: {track.kind}")

    # Get local media (Audio Only)
    try:
        # Use Media Player to capture audio from the default device
        # 'default:audio' with 'dshow' (Windows), 'avfoundation' (macOS), 'v4l2' (Linux for video, check for audio too)
        # Using format=None lets aiortc try to auto-detect.

        # local_player = MediaPlayer(MEDIA_SOURCE, format=None)
        # if not local_player.audio:
        #     raise Exception("Could not open local audio device.")

        pc.addTrack(GeminiOutputTrack())
        print("Added Gemini live audio track.")

    except Exception as e:
        print(f"ERROR: Could not get local audio from '{MEDIA_SOURCE}'. Please check device or try a test audio file.")
        print(f"Error details: {e}")
        # Fallback if no audio device/file works, though connection will be silent
        print("Continuing without local audio. Remote audio might still work if peer sends.")
        local_player = None # Ensure player is None if it failed

    print("RTCPeerConnection created and local audio added (if successful).")
    return pc

async def cleanup_webrtc():
    global pc, local_player, recorder, remote_audio_track
    if pc:
        try:
            await pc.close()
        except Exception as e:
            print(f"Error closing peer connection: {e}")
        pc = None
    
    if local_player:
        try:
            local_player._stop() # Close MediaPlayer
        except Exception as e:
            print(f"Error closing local media player: {e}")
        local_player = None

    if recorder:
        try:
            if recorder: # Only stop if it's actually recording
                await recorder.stop()
        except Exception as e:
            print(f"Error stopping recorder: {e}")
        recorder = None
    
    remote_audio_track = None
    print("WebRTC cleanup complete.")


# --- Socket.IO Event Handlers ---
@sio.event
async def connect():
    print(f"[Socket.IO] Connected to server! My ID: {caller_id}, Socket SID: {sio.sid}")
    # Display caller ID on connection
    print(f"\nYour Caller ID: {caller_id}")
    await show_main_menu()

@sio.event
async def disconnect():
    print("[Socket.IO] Disconnected from server.")
    await cleanup_webrtc()
    sys.exit(0)

@sio.event
async def newCall(data):
    global other_user_id, remote_rtc_message
    print(f"\n[Signaling] Incoming call from {data.get('callerId')}!")
    if pc and pc.connectionState != "closed":
        print("Already in a call or connection active. Rejecting new call.")
        # You might want to send a 'rejectCall' signal back to the caller
        return

    other_user_id = data.get('callerId')
    remote_rtc_message = data.get('rtcMessage')

    print(f"Call from: {other_user_id}")
    print("Type 'accept' to answer or 'reject' to decline.")

@sio.event
async def callAnswered(data):
    global remote_rtc_message
    print(f"\n[Signaling] Call answered by {data.get('callee')}")
    set_remote_rtc_message(data.get('rtcMessage'))

    if pc and pc.signalingState != "stable":
        try:
            await pc.setRemoteDescription(RTCSessionDescription(
                sdp=remote_rtc_message['sdp'],
                type=remote_rtc_message['type']
            ))
            print("Remote description set from answer.")
            print("WebRTC connection established. Type 'hangup' to end.")
        except Exception as e:
            print(f"Error setting remote description from answer: {e}")
    else:
        print("PeerConnection not ready to set remote description (answer).")

@sio.event
async def ICEcandidate(data):
    print(f"[Signaling] Received ICE candidate from {data.get('sender')}")
    rtcMessage = data.get('rtcMessage')
    candidate = rtcMessage["candidate"].split()

    if pc and pc.remoteDescription:
        try:
            await pc.addIceCandidate(
                RTCIceCandidate(
                    foundation=candidate[0].split(":")[1],
                    component=int(candidate[1]),
                    protocol=candidate[2],
                    priority=int(candidate[3]),
                    ip=candidate[4],
                    port=int(candidate[5]),
                    type=candidate[7],
                    sdpMid=rtcMessage["id"],
                    sdpMLineIndex=rtcMessage["label"]
                )
            )
            print("Added remote ICE candidate.")
        except Exception as e:
            print(f"Error adding ICE candidate: {e}")
    else:
        print("PeerConnection not initialized to add ICE candidate.")

@sio.event
async def force_disconnect(data):
    print(f"\n[Signaling] Server forced disconnect: {data.get('message')}")
    await cleanup_webrtc()
    print("Call ended by server. Type 'menu' to go back to the main menu.")
    await show_main_menu()

# --- Call Flow Functions ---
async def start_call_process():
    global pc
    await create_peer_connection()
 
    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)  

        send_call({
            'calleeId': other_user_id,
            'rtcMessage': {
                'type': pc.localDescription.type,
                'sdp': pc.localDescription.sdp,
            },
        })
        print("RTC => Offer sent. Waiting for answer from remote peer...")
    except Exception as e:
        print(f"Error creating/sending offer in start_call_process: {e}")
        await cleanup_webrtc()

async def accept_call_process():
    global pc
    if not remote_rtc_message:
        print("No incoming call to accept.")
        return

    await create_peer_connection() # Create new PC for the answerer

    try:
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=remote_rtc_message['sdp'],
            type=remote_rtc_message['type']
        ))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        answer_call({
            'callerId': other_user_id, # Target of the answer
            'rtcMessage': {
                'type': pc.localDescription.type,
                'sdp': pc.localDescription.sdp,
            },
        })
        print("Answer created and sent. WebRTC connection establishing...")
        print("Type 'hangup' to end the call.")
    except Exception as e:
        print(f"Error accepting call: {e}")
        await cleanup_webrtc()


async def hangup_call():
    global pc
    if pc:
        print("Hanging up call...")
        await cleanup_webrtc()
    else:
        print("No active call to hang up.")
    set_other_user_id(None)
    set_remote_rtc_message(None)
    print("Type 'menu' to go back to the main menu.")
    await show_main_menu()


# --- CLI and Main Loop ---
async def show_main_menu():
    print("\n--- Main Menu ---")
    print(f"Your Caller ID: {caller_id}")
    print("1. Call another user (type 'call')")
    print("2. Hang up current call (type 'hangup')")
    print("3. Toggle Mic (type 'mic')")
    print("4. Exit (type 'exit')")
    print("-----------------")

async def toggle_mic():
    global local_mic_on
    if local_player and local_player.audio:
        local_mic_on = not local_mic_on
        local_player.audio.enabled = local_mic_on
        print(f"Microphone is now {'ON' if local_mic_on else 'OFF'}")
    else:
        print("Local audio stream not available from player.")


async def input_loop():
    while True:
        try:
            command = await asyncio.to_thread(input, "> ") # Run input in a separate thread
            command = command.strip().lower()

            if command == 'call':
                if pc and pc.connectionState != "closed":
                    print("Already in a call or connection active. Please hangup first.")
                    continue
                target_id = await asyncio.to_thread(input, "Enter other user ID to call: ")
                target_id = target_id.strip()
                if target_id and target_id != caller_id:
                    set_other_user_id(target_id)
                    await start_call_process()
                else:
                    print("Invalid target ID.")
            elif command == 'accept':
                if other_user_id and remote_rtc_message:
                    await accept_call_process()
                else:
                    print("No incoming call to accept.")
            elif command == 'reject':
                print("Call rejected.")
                set_other_user_id(None)
                set_remote_rtc_message(None)
                await show_main_menu()
            elif command == 'hangup':
                await hangup_call()
            elif command == 'mic':
                await toggle_mic()
            elif command == 'menu':
                await show_main_menu()
            elif command == 'exit':
                print("Exiting...")
                if sio.connected:
                    await sio.disconnect()
                await cleanup_webrtc()
                break
            else:
                print("Unknown command. Type 'menu' for options.")
        except EOFError: # Handles Ctrl+D or similar
            print("\nExiting due to EOF.")
            break
        except Exception as e:
            print(f"An error occurred in input loop: {e}")
            break

async def main():
    # Connect to your signaling server
    # Replace 'http://10.10.10.124:3500' with your server's actual address if different
    await sio.connect(f'http://10.10.10.124:3500?callerId={caller_id}')

    # Start the CLI input loop
    await input_loop()

    # Wait for the Socket.IO client to disconnect gracefully
    await sio.wait()

if __name__ == '__main__':
    # Set the log level for aiortc (optional, for debugging)
    # import logging
    # logging.basicConfig(level=logging.DEBUG)
    
    # Run the main asynchronous function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient terminated by user.")
    finally:
        # Ensure resources are cleaned up on exit
        asyncio.run(cleanup_webrtc())
        if sio.connected:
            asyncio.run(sio.disconnect())