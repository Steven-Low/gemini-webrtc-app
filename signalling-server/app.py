import os
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, join_room, emit, disconnect

# Initialize Flask app
app = Flask(__name__, static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")

# A simple dictionary to map SocketIO session IDs (sid) to user IDs (callerId)
socketio.sid_to_user_map = {}

# Route to serve the main HTML file (e.g., index.html)
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# Route to serve any other static files (CSS, JS, images, etc.)
@app.route('/<path:path>')
def serve_other_static_files(path):
    return send_from_directory(app.static_folder, path)

# Route to expose current sid user map for debugging
@app.route('/debug/sessions')
def debug_sessions():
    return jsonify(socketio.sid_to_user_map)

# --- Socket.IO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    """
    Handles new client connections.
    Extracts 'callerId' from the handshake query using Flask's 'request' object.
    """
    caller_id = None
    # Access handshake query parameters using Flask's request object
    # request.args is a dictionary-like object for query parameters
    if 'callerId' in request.args:  
        caller_id = request.args.get('callerId')  
        
        # Store the callerId using the current session ID (sid)
        socketio.sid_to_user_map[request.sid] = caller_id  

        # Join a room named after the callerId for direct messaging
        join_room(caller_id)
        print(f"'{caller_id}' (SID: {request.sid}) Connected")

        # Optionally emit a response back to the connected client
        emit('my response', {'data': 'Connected to Python server!', 'id': caller_id})
    else:
        print(f"Anonymous user (SID: {request.sid}) Connected")  
        emit('my response', {'data': 'Connected to Python server! (Anonymous)'})


@socketio.on('call')
def handle_call(data):
    """
    Handles a 'call' event from a client (initiating a call).
    Forwards the call request to the 'calleeId'.
    """
    callee_id = data.get('calleeId')
    rtc_message = data.get('rtcMessage')

    # Get the callerId from our map using the current socket's session ID
    caller_id = socketio.sid_to_user_map.get(request.sid)  

    if callee_id and rtc_message and caller_id:
        print(f"Call from '{caller_id}' to '{callee_id}'")
        # Emit 'newCall' event to the callee's room
        emit('newCall', {
            'callerId': caller_id,
            'rtcMessage': rtc_message
        }, room=callee_id)
    else:
        print(f"Invalid 'call' data received from {caller_id}: {data}")


@socketio.on('answerCall')
def handle_answer_call(data):
    """
    Handles an 'answerCall' event from a client (answering a call).
    Forwards the answer to the original 'callerId'.
    """
    caller_id = data.get('callerId')
    rtc_message = data.get('rtcMessage')

    # Get the callee (current user) ID from our map
    callee_id = socketio.sid_to_user_map.get(request.sid)  

    if caller_id and rtc_message and callee_id:
        print(f"Call answered by '{callee_id}' for '{caller_id}'")
        # Emit 'callAnswered' event to the caller's room
        emit('callAnswered', {
            'callee': callee_id,
            'rtcMessage': rtc_message
        }, room=caller_id)
    else:
        print(f"Invalid 'answerCall' data received from {callee_id}: {data}")
        
@socketio.on('hangupCall')
def handle_hangup_call(data):
    """
    Handles a 'hangupCall' event from a client (ending a call).
    Notifies the other participant that the call has ended.
    """
    target_id = data.get('targetId')  
    sender_id = socketio.sid_to_user_map.get(request.sid)

    if target_id and sender_id:
        print(f"'{sender_id}' hung up on '{target_id}'")
        emit('callEnded', {
            'senderId': sender_id
        }, room=target_id)
    else:
        print(f"Invalid 'hangupCall' data from {sender_id}: {data}")


@socketio.on('ICEcandidate')
def handle_ice_candidate(data):
    """
    Handles an 'ICEcandidate' event for WebRTC peer connection.
    Forwards the ICE candidate to the specified 'calleeId'.
    """
    callee_id = data.get('calleeId')
    rtc_message = data.get('rtcMessage')

    # Get the sender (current user) ID from our map
    sender_id = socketio.sid_to_user_map.get(request.sid) 

    print(f"ICEcandidate data.calleeId: {callee_id}")
    print(f"ICEcandidate from sender: {sender_id}")

    if callee_id and rtc_message and sender_id:
        # Emit 'ICEcandidate' event to the callee's room
        emit('ICEcandidate', {
            'sender': sender_id,
            'rtcMessage': rtc_message
        }, room=callee_id)
    else:
        print(f"Invalid 'ICEcandidate' data received from {sender_id}: {data}")


@socketio.on('disconnect')
def handle_disconnect():
    """
    Handles client disconnections.
    Removes the user from our tracking map.
    """
    # Remove the user from our map upon disconnection
    user_id = socketio.sid_to_user_map.pop(request.sid, 'Unknown')  
    print(f"'{user_id}' (SID: {request.sid}) Disconnected") 


# --- Main execution block ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3500))
    print(f"Server starting on {os.environ.get('HOSTNAME', 'Unknown host') or os.uname().nodename}:{port}")
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True) # Listen to all interfacess 0.0.0.0