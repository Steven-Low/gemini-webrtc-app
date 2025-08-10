import React, {useEffect, useState, useRef, useMemo} from 'react'; // BUG 2 FIX: Imported useMemo
import {
  Platform,
  KeyboardAvoidingView,
  TouchableWithoutFeedback,
  Keyboard,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Animated,
  Dimensions,
  AppState
} from 'react-native';
import TextInputContainer from './components/TextInputContainer';
import SocketIOClient from 'socket.io-client';
import PushNotification from 'react-native-push-notification';
import {
  mediaDevices,
  RTCPeerConnection,
  RTCView,
  RTCIceCandidate,
  RTCSessionDescription,
} from 'react-native-webrtc';
import CallEnd from './asset/CallEnd';
import CallAnswer from './asset/CallAnswer';
import MicOn from './asset/MicOn';
import MicOff from './asset/MicOff';
import VideoOn from './asset/VideoOn';
import VideoOff from './asset/VideoOff';
import CameraSwitch from './asset/CameraSwitch';
import IconContainer from './components/IconContainer';
import InCallManager from 'react-native-incall-manager';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { getCallerId } from './Session';

const { width } = Dimensions.get('window');

export default function App({}) {
  const [localStream, setlocalStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const [type, setType] = useState('JOIN');
  const socketRef = useRef(null);
  const [socketAddress, setSocketAddress] = useState('http://10.10.10.124:3500');
  const [isMenuVisible, setIsMenuVisible] = useState(false);
  const [otherUserId, setOtherUserId] = useState(null);       // fOR SYNCRHONOUS SHXT (UI)
  const otherUserIdRef = useRef(otherUserId);                 // fOR ASYNCRONOUSE SHXT (RTC)
  const [localMicOn, setlocalMicOn] = useState(true);
  const [localWebcamOn, setlocalWebcamOn] = useState(false);  // Default video off
  const appState = useRef(AppState.currentState);
  const [callerId, setCallerId] = useState("111111");
  const peerConnectionRef = useRef(null);
  let remoteRTCMessage = useRef(null);

    // Load initial data from storage when the app first mounts
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const savedAddress = await AsyncStorage.getItem('SOCKET_ADDRESS');
        if (savedAddress) {
          setSocketAddress(savedAddress);
        }

        const savedCallerId = await AsyncStorage.getItem('SAVED_CALLER_ID');
        if (savedCallerId) {
          console.log('Loaded fixed Caller ID:', savedCallerId);
          setCallerId(savedCallerId);
        } else {
          const newId = getCallerId(); // getCallerId should be a simple non-hook function
          console.log('Generated new Caller ID:', newId);
          setCallerId(newId);
        }
      } catch (e) {
        console.warn('Failed to load initial data', e);
        // Fallback in case of storage error
        if (!callerId) {
          setCallerId(getCallerId());
        }
      }
    };
    loadInitialData();
  }, []);
 
 // +++ ADD THIS useEFFECT HOOK for notification setup +++
  useEffect(() => {
    // 1. Configure what happens when a notification is tapped
    PushNotification.configure({
      onNotification: function (notification) {
        console.log("NOTIFICATION TAPPED:", notification);

        // Bring the app to the incoming call screen
        if (notification.data) {
          remoteRTCMessage.current = notification.data.rtcMessage;
          setOtherUserId(notification.data.callerId);
          setType('INCOMING_CALL');
        }
        // This is required on iOS to handle completion of the notification task
        notification.finish && notification.finish();
      },
      requestPermissions: Platform.OS === 'ios',
    });

    // 2. Create the notification channel for Android
    PushNotification.createChannel(
      {
        channelId: "incoming-calls", // Must be a unique ID
        channelName: "Incoming Calls",
        channelDescription: "Notifications for new calls",
        soundName: "default",
        importance: 4, // High importance
        vibrate: true,
      },
      (created) => console.log(`Notification channel 'incoming-calls' returned '${created}'`)
    );

    // 3. Listen for changes in the app's state (foreground/background)
    const subscription = AppState.addEventListener('change', nextAppState => {
        appState.current = nextAppState;
        console.log('AppState changed to:', appState.current);
    });

    return () => {
        subscription.remove();
    };
  }, []);  


  useEffect(() => {
    otherUserIdRef.current = otherUserId;
  }, [otherUserId]);

 
  useEffect(() => {
    // 1. Wait until we have the necessary connection parameters
    if (!socketAddress || !callerId) {
      return;
    }

    console.log(`--- Setting up connections for Caller ID: ${callerId} ---`);

    // --- 2. Create the Peer Connection and Socket ---
    const pc = new RTCPeerConnection({
      iceServers: [
        {urls: 'stun:stun.l.google.com:19302'},
        {urls: 'stun:stun1.l.google.com:19302'},
        {urls: 'stun:stun2.l.google.com:19302'},
      ],
    });
    peerConnectionRef.current = pc;

    const socket = SocketIOClient(socketAddress, {
      transports: ['websocket'],
      query: { callerId },
    });
    socketRef.current = socket;

    // --- 3. Set up ALL event listeners ---
    
    // WebRTC Listeners
    pc.onaddstream = event => {
      console.log("Remote stream received");
      setRemoteStream(event.stream);
    };

    pc.onicecandidate = event => {
      if (event.candidate && socketRef.current) {
        socketRef.current.emit('ICEcandidate', {
          calleeId: otherUserIdRef.current,
          rtcMessage: event.candidate,
        });
      }
    };

    // Media Device Setup
    mediaDevices.enumerateDevices().then(sourceInfos => {
        let videoSourceId;
        for (let i = 0; i < sourceInfos.length; i++) {
          const sourceInfo = sourceInfos[i];
          if (
            sourceInfo.kind == 'videoinput' &&
            sourceInfo.facing == 'user'
          ) {
            videoSourceId = sourceInfo.deviceId;
          }
        }
  
        mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true
            },
            video: {
              mandatory: { minWidth: 500, minHeight: 300, minFrameRate: 20 },
              facingMode: 'user',
              optional: videoSourceId ? [{sourceId: videoSourceId}] : [],
            },
          })
          .then(stream => {
            if (!localWebcamOn){
              stream.getVideoTracks().forEach(track => (track.enabled = false));
            }
            setlocalStream(stream);
            if (peerConnectionRef.current) {
                peerConnectionRef.current.addStream(stream);
            }
          });
      });

    // Socket Listeners
    socket.on('newCall', data => {
      if (appState.current.match(/inactive|background/)) {
        PushNotification.localNotification({
          channelId: "incoming-calls",
          title: `Incoming Call from ${data.callerId}`,
          message: "Tap to answer.",
          userInfo: data,
        });
      } else {
        remoteRTCMessage.current = data.rtcMessage;
        setOtherUserId(data.callerId);
        setType('INCOMING_CALL');
      }
    });

    socket.on('callAnswered', data => {
      remoteRTCMessage.current = data.rtcMessage;
      if (peerConnectionRef.current) {
        peerConnectionRef.current.setRemoteDescription(new RTCSessionDescription(remoteRTCMessage.current));
      }
      setType('WEBRTC_ROOM');
    });

    socket.on('callEnded', data => {
      if (data.targetId === callerId) {
        leave(false);
      }
    });

    socket.on('ICEcandidate', data => {
      if (peerConnectionRef.current) {
        peerConnectionRef.current.addIceCandidate(new RTCIceCandidate(data.rtcMessage));
      }
    });

    // --- 4. Return the Master Cleanup Function ---
    // This runs when the component unmounts OR when socketAddress/callerId changes.
    return () => {
      console.log("--- Tearing down old connections ---");
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
      if (peerConnectionRef.current) {
        peerConnectionRef.current.close();
        peerConnectionRef.current = null;
      }
    };
  }, [socketAddress, callerId]);

  useEffect(() => {
    InCallManager.start();
    InCallManager.setKeepScreenOn(true);
    InCallManager.setForceSpeakerphoneOn(true);

    return () => {
      InCallManager.stop();
    };
  }, []);

  function sendICEcandidate(data) {
    socketRef.current.emit('ICEcandidate', data);
  }

  async function processCall() {
    const sessionDescription = await peerConnectionRef.current.createOffer();
    await peerConnectionRef.current.setLocalDescription(sessionDescription);
    sendCall({
      calleeId: otherUserIdRef.current,
      rtcMessage: sessionDescription,
    });
  }

  async function processAccept() {
    peerConnectionRef.current.setRemoteDescription(
      new RTCSessionDescription(remoteRTCMessage.current),
    );
    const sessionDescription = await peerConnectionRef.current.createAnswer();
    await peerConnectionRef.current.setLocalDescription(sessionDescription);
    answerCall({
      callerId: otherUserIdRef.current,
      rtcMessage: sessionDescription,
    });
  }

  function answerCall(data) {
    socketRef.current.emit('answerCall', data);
  }

  function sendCall(data) {
    socketRef.current.emit('call', data);
  }

  function hangupCall(data) {
    socketRef.current.emit('hangupCall', data)
  }

   function leave(notify = true) {
    console.log("Leave function called.");
    
    // 1. Notify the other peer that you are hanging up
    if (notify && socketRef.current) {
      socketRef.current.emit('hangupCall', {
        targetId: otherUserIdRef.current,
        senderId: callerId 
      });
    }
    
    // 2. Close the current peer connection
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      // The main useEffect will create a new RTCPeerConnection when the next call starts.
      // We don't need to create one here.
    }
    
    // 3. Reset the UI state to go back to the join screen
    setRemoteStream(null);
    setOtherUserId(null); // Also reset the other user's ID
    setType('JOIN');
  }


  const JoinScreen = () => {
    return (
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={{
            flex: 1,
            backgroundColor: '#050A0E',
            justifyContent: 'center',
            paddingHorizontal: 42,
          }}>
          <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
            <>
              <View
                style={{
                  padding: 35,
                  backgroundColor: '#1A1C22',
                  justifyContent: 'center',
                  alignItems: 'center',
                  borderRadius: 14,
                }}>
                <Text
                  style={{
                    fontSize: 18,
                    color: '#D0D4DD',
                  }}>
                  Your Caller ID
                </Text>
                <View
                  style={{
                    flexDirection: 'row',
                    marginTop: 12,
                    alignItems: 'center',
                  }}>
                  <Text
                    style={{
                      fontSize: 32,
                      color: '#ffff',
                      letterSpacing: 6,
                    }}>
                    {callerId}
                  </Text>
                </View>
              </View>
  
              <View
                style={{
                  backgroundColor: '#1A1C22',
                  padding: 40,
                  marginTop: 25,
                  justifyContent: 'center',
                  borderRadius: 14,
                }}>
                <Text
                  style={{
                    fontSize: 18,
                    color: '#D0D4DD',
                  }}>
                  Enter call id of another user
                </Text>
                <TextInputContainer
                  placeholder={'Enter Caller ID'}
                  value={otherUserId}
                  setValue={setOtherUserId}
                  keyboardType={'number-pad'}
                />
                <TouchableOpacity
                  onPress={() => {
                    setType('OUTGOING_CALL');
                    processCall();
                  }}
                  style={{
                    height: 50,
                    backgroundColor: '#5568FE',
                    justifyContent: 'center',
                    alignItems: 'center',
                    borderRadius: 12,
                    marginTop: 16,
                  }}>
                  <Text
                    style={{
                      fontSize: 16,
                      color: '#FFFFFF',
                    }}>
                    Call Now
                  </Text>
                </TouchableOpacity>
              </View>
              {/* Settings Button */}
              <TouchableOpacity 
                style={{
                  position: 'absolute',
                  top: 20,
                  right: 20,
                  backgroundColor: '#5568FE',
                  paddingVertical: 10,
                  paddingHorizontal: 15,
                  borderRadius: 12,
                  zIndex: 10, // Ensure it's above other elements
                }} 
                onPress={() => setIsMenuVisible(true)}>
                <Text style={ {
                  color: '#FFFFFF',
                  fontWeight: 'bold',
                }}>Settings</Text>
              </TouchableOpacity>
            </>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      );
  };

  const OutgoingCallScreen = () => {
    // Unchanged...
    return (
        <View
          style={{
            flex: 1,
            justifyContent: 'space-around',
            backgroundColor: '#050A0E',
          }}>
          <View
            style={{
              padding: 35,
              justifyContent: 'center',
              alignItems: 'center',
              borderRadius: 14,
            }}>
            <Text
              style={{
                fontSize: 16,
                color: '#D0D4DD',
              }}>
              Calling to...
            </Text>
  
            <Text
              style={{
                fontSize: 36,
                marginTop: 12,
                color: '#ffff',
                letterSpacing: 6,
              }}>
              {otherUserId}
            </Text>
          </View>
          <View
            style={{
              justifyContent: 'center',
              alignItems: 'center',
            }}>
            <TouchableOpacity
              onPress={() => {
                setType('JOIN');
                setOtherUserId(null) 
                leave(true); // Make sure to call leave to clean up
              }}
              style={{
                backgroundColor: '#FF5D5D',
                borderRadius: 30,
                height: 60,
                aspectRatio: 1,
                justifyContent: 'center',
                alignItems: 'center',
              }}>
              <CallEnd width={50} height={12} />
            </TouchableOpacity>
          </View>
        </View>
      );
  };

  const IncomingCallScreen = () => {
    // Unchanged...
    return (
        <View
          style={{
            flex: 1,
            justifyContent: 'space-around',
            backgroundColor: '#050A0E',
          }}>
          <View
            style={{
              padding: 35,
              justifyContent: 'center',
              alignItems: 'center',
              borderRadius: 14,
            }}>
            <Text
              style={{
                fontSize: 36,
                marginTop: 12,
                color: '#ffff',
              }}>
              {otherUserId} is calling..
            </Text>
          </View>
          <View
            style={{
              justifyContent: 'center',
              alignItems: 'center',
            }}>
            <TouchableOpacity
              onPress={() => {
                processAccept();
                setType('WEBRTC_ROOM');
              }}
              style={{
                backgroundColor: 'green',
                borderRadius: 30,
                height: 60,
                aspectRatio: 1,
                justifyContent: 'center',
                alignItems: 'center',
              }}>
              <CallAnswer height={28} fill={'#fff'} />
            </TouchableOpacity>
          </View>
        </View>
      );
  };

  function switchCamera() {
    localStream.getVideoTracks().forEach(track => {
      track._switchCamera();
    });
  }

  function toggleCamera() {
    localWebcamOn ? setlocalWebcamOn(false) : setlocalWebcamOn(true);
    localStream.getVideoTracks().forEach(track => {
      localWebcamOn ? (track.enabled = false) : (track.enabled = true);
    });
  }

  function toggleMic() {
    localMicOn ? setlocalMicOn(false) : setlocalMicOn(true);
    localStream.getAudioTracks().forEach(track => {
      localMicOn ? (track.enabled = false) : (track.enabled = true);
    });
  }

  const WebrtcRoomScreen = () => {
    // Unchanged...
    return (
        <View
          style={{
            flex: 1,
            backgroundColor: '#050A0E',
            paddingHorizontal: 12,
            paddingVertical: 12,
          }}>
          {localStream ? (
            <RTCView
              objectFit={'cover'}
              style={{flex: 1, backgroundColor: '#050A0E'}}
              streamURL={localStream.toURL()}
            />
          ) : null}
          {remoteStream ? (
            <RTCView
              objectFit={'cover'}
              style={{
                flex: 1,
                backgroundColor: '#050A0E',
                marginTop: 8,
              }}
              streamURL={remoteStream.toURL()}
            />
          ) : null}
          <View
            style={{
              marginVertical: 12,
              flexDirection: 'row',
              justifyContent: 'space-evenly',
            }}>
            <IconContainer
              backgroundColor={'red'}
              onPress={() => {
                leave(true);
              }}
              Icon={() => {
                return <CallEnd height={26} width={26} fill="#FFF" />;
              }}
            />
            <IconContainer
              style={{
                borderWidth: 1.5,
                borderColor: '#2B3034',
              }}
              backgroundColor={!localMicOn ? '#fff' : 'transparent'}
              onPress={() => {
                toggleMic();
              }}
              Icon={() => {
                return localMicOn ? (
                  <MicOn height={24} width={24} fill="#FFF" />
                ) : (
                  <MicOff height={28} width={28} fill="#1D2939" />
                );
              }}
            />
            <IconContainer
              style={{
                borderWidth: 1.5,
                borderColor: '#2B3034',
              }}
              backgroundColor={!localWebcamOn ? '#fff' : 'transparent'}
              onPress={() => {
                toggleCamera();
              }}
              Icon={() => {
                return localWebcamOn ? (
                  <VideoOn height={24} width={24} fill="#FFF" />
                ) : (
                  <VideoOff height={36} width={36} fill="#1D2939" />
                );
              }}
            />
            <IconContainer
              style={{
                borderWidth: 1.5,
                borderColor: '#2B3034',
              }}
              backgroundColor={'transparent'}
              onPress={() => {
                switchCamera();
              }}
              Icon={() => {
                return <CameraSwitch height={24} width={24} fill="#FFF" />;
              }}
            />
          </View>
        </View>
      );
  };

    // Settings Menu Component
  const SettingsMenu = ({ isVisible, onClose, onSave }) => {
    const [tempAddress, setTempAddress] = useState(socketAddress);
    const [tempCallerId, setTempCallerId] = useState(callerId); 
    const slideAnim = useRef(new Animated.Value(width)).current;

    useEffect(() => {
      Animated.timing(slideAnim, {
        toValue: isVisible ? 0 : width,
        duration: 300,
        useNativeDriver: true,
      }).start();
    }, [isVisible, slideAnim]);

    const handleSave = () => {
      onSave(tempAddress, tempCallerId);
      onClose();
    };

    if (!isVisible) return null;

    return (
      <View style={{
        position: 'absolute',
        ...StyleSheet.absoluteFillObject,
        zIndex: 100,
      }}>
        <TouchableWithoutFeedback onPress={onClose}>
          <View style={{
            ...StyleSheet.absoluteFillObject,
            backgroundColor: 'rgba(0,0,0,0.5)',
          }} />
        </TouchableWithoutFeedback>
        <Animated.View style={{
          position: 'absolute',
          top: 0,
          right: 0,
          width: width * 0.75, // 75% of screen width
          height: '100%',
          backgroundColor: '#1A1C22',
          padding: 20,
          transform: [{ translateX: slideAnim }],
        }}>
          <View style={{
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 20,
          }}>
            <Text style={{
              color: '#FFFFFF',
              fontSize: 24,
              fontWeight: 'bold',
            }}>
              Settings
            </Text>
            <TouchableOpacity onPress={onClose}>
              <Text style={{
                color: '#5568FE',
                fontSize: 16,
              }}>
                Close
              </Text>
            </TouchableOpacity>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={{
              color: '#D0D4DD',
              fontSize: 16,
              marginBottom: 10,
            }}>
              Socket Server Address
            </Text>
            <TextInputContainer
              placeholder={'e.g. http://10.10.10.1:3500'}
              value={tempAddress}
              setValue={setTempAddress}
              keyboardType={'default'}
            />
            <Text style={{
              color: '#D0D4DD',
              fontSize: 16,
              marginBottom: 10,
            }}>
              Your Fixed Caller ID
            </Text>
            <TextInputContainer
              placeholder={'Enter a fixed ID'}
              value={tempCallerId}
              setValue={setTempCallerId}
              keyboardType={'number-pad'}
            />

            <TouchableOpacity
              onPress={handleSave}
              style={{
                height: 50,
                backgroundColor: '#5568FE',
                justifyContent: 'center',
                alignItems: 'center',
                borderRadius: 12,
                marginTop: 20,
              }}>
              <Text style={{
                color: '#FFFFFF',
                fontSize: 16,
                fontWeight: 'bold',
              }}>
                Save
              </Text>
            </TouchableOpacity>
          </View>
        </Animated.View>
      </View>
    );
  };
  
  const renderScreen = () => {
    let screen;
    switch (type) {
      case 'JOIN':
        screen = JoinScreen();
        break;
      case 'INCOMING_CALL':
        screen = IncomingCallScreen();
        break;
      case 'OUTGOING_CALL':
        screen = OutgoingCallScreen();
        break;
      case 'WEBRTC_ROOM':
        screen = WebrtcRoomScreen();
        break;
      default:
        screen = null;
    }
    
    return (
      <View style={{ flex: 1 }}>
        {screen}
        <SettingsMenu
          isVisible={isMenuVisible}
          onClose={() => setIsMenuVisible(false)}
          onSave={async (newAddress, newCallerId) => {
            try {
              await AsyncStorage.setItem('SOCKET_ADDRESS', newAddress);
              setSocketAddress(newAddress);
            } catch (e) {
              console.warn('Failed to save socket address', e);
            }
            try {
              await AsyncStorage.setItem('SAVED_CALLER_ID', newCallerId);
              setCallerId(newCallerId);
            } catch (e) {
              console.warn('Failed to save caller id', e)
            }
            setIsMenuVisible(false);
          }}
        />
      </View>
    );
  };

  return renderScreen();

}