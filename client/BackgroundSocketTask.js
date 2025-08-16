import BackgroundService from 'react-native-background-actions';
import SocketIOClient from 'socket.io-client';
import PushNotification from 'react-native-push-notification';

let socket = null;

const backgroundSocketTask = async (taskData) => {
    const { socketAddress, callerId, onNewCall } = taskData;

    await new Promise((resolve) => {
        // --- Connect Socket.IO ---
        socket = SocketIOClient(socketAddress, {
            transports: ['websocket'],
            query: { callerId },
        });

        socket.on('connect', () => {
            console.log('[Background Task] Socket connected!');
        });

        // --- Listen for New Calls ---
        socket.on('newCall', (data) => {
            console.log('[Background Task] Received new call via socket.');
            // This calls the function we will pass from our App.js
            onNewCall(data); 
        });

        socket.on('disconnect', () => {
            console.log('[Background Task] Socket disconnected!');
        });

        // Keep the background task running
    });
};

const options = {
    taskName: 'SocketManager',
    taskTitle: 'App is running',
    taskDesc: 'Listening for incoming calls',
    taskIcon: {
        name: 'ic_launcher',
        type: 'mipmap',
    },
    linkingURI: 'yourappscheme://', // For when the notification is clicked
    parameters: {
        // We will pass our socket details here
    },
};

export const startBackgroundSocket = (socketAddress, callerId, onNewCall) => {
    // Update parameters before starting
    options.parameters = { socketAddress, callerId, onNewCall };

    BackgroundService.start(backgroundSocketTask, options)
        .then(() => console.log('Background socket service started successfully.'))
        .catch(err => console.error('Error starting background service:', err));
};

export const stopBackgroundSocket = () => {
    if (socket) {
        socket.disconnect();
    }
    BackgroundService.stop()
        .then(() => console.log('Background socket service stopped successfully.'))
        .catch(err => console.error('Error stopping background service:', err));
};

// Export the socket instance so our main app can still use it for emitting
export const getSocket = () => socket;