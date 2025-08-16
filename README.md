# Gemini WebRTC React Native App with Signalling
Are you frustrated with all those paid api keys or plan? What the hell PipeCat by Daily? (Restrict my plan to 168 hours per month?) I want my super intelligence AI to be slaved 24/7 and no bill!

<img src="./public/gemini-webrtc.png" />

> ### Why Choosing Gemini Live Api Plus Webrtc?
>- **Fast Response Time < 0.5s** : Almost identical to talking or response to people in real
>- **Integrated VAD**: Voice Activity Detection on gemini socket fast and accurate
>- **Interrupt detection**: The response stream can be interrupted through VAD 
>- **Free to use** : The live model can has at most 3 concurrent session lasting forever
>- **Echo Cancellation**: The speaker and microphone will not interfere
>- **Automatic Gain Control (AGC)**: Adjust the volume and output (from client side)
>- **Noise Suppression**: Reduce background noise
>- **Tool Use**: Both synchronous and asynchronous function calling is available
>- **[NEW] Open Wake Word**: Can wake up anytime or switch into active standby mode


---

## Roadmap
- [x] Establish client <--> gemini client <--> gemini websocket connection for 24/7
- [ ] Home Assistant Integration



## Run the Sample App

Clone the repository to your local environment.

```js
git clone https://github.com/Steven-Low/gemini-webrtc-app.git
```

### Server Setup

#### Step 1: Go to server folder

```js

cd gemini-webrtc-app/server

```

#### Step 2: Install Dependency

```js

npm install
```

#### Step 3: Run the project

```js

npm run start
```

---

### Gemini Client Setup
#### Step 1: Go to client-python folder
```js
cd gemini-webrtc-app/client-python
```

#### Step 2: Create & activate virtual python environment
```
python3 -m venv venv
source ./venv/bin/activate
```

#### Step 3: Install the dependencies
```
pip install -r requirements.txt
```

#### Step 4: Set your Gemini api-key in .env file
```
GOOGLE_API_KEY=sk-xxxxx
```

#### Step 5: Run the Gemini client
```
python app.py
```

### User Client Setup

#### Step 1: Go to client folder

```js

cd gemini-webrtc-app/client
```

### Step 2: Install the dependecies

```js
npm install
```

### Step 3: Provide your local Ip address in `SocketIOClient`.

in App.js file, update the Network Ip address.

```js
const socket = SocketIOClient("http://192.168.2.201:3500", {});
```

### Step 4: Run the react builder server
```js
npm run start
```

### Step 5: Connect adb devices
replace 04e8 with your devices first 4 digits id via `lsusb`
```
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev"' | sudo tee /etc/udev/rules.d/51-android-usb.rules
adb devices 
```

### Step 6: Run your Application :D
> Before you proceed, please ensure you have setup the environment correctly: https://reactnative.dev/docs/set-up-your-environment
```js
npm run android
npm run ios
```

