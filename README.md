# Gemini WebRTC React Native App with Signalling
Are you frustrated with all those paid api keys or plan? What the hell PipeCat by Daily? (Restrict my plan to 168 hours per month?) I want my super intelligence AI to be slaved 24/7 and no bill!

> ### Why Choosing Gemini Live Api ?
>- It is because the average fast response time can achieve < 0.5 seconds, almost identical to talking to someone and he or she respond (Not even considering the uhhh umm noise when they speak)
>- Another cool reason is it is free! 🩷 Love you Goooooooogle.

<img src="./public/react-native-webrtc-app.jpeg" />

---

## Roadmap
- [x] Establish client <--> gemini client <--> gemini websocket connection for 24/7
- [ ] Home Assistant Integration



## Run the Sample App

Clone the repository to your local environment.

```js
git clone https://github.com/Steven-Low/react-native-webrtc-app
```

### Server Setup

#### Step 1: Go to server folder

```js

cd react-native-webrtc-app/server

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
cd react-native-webrtc-app/client-python
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

cd react-native-webrtc-app/client
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
```js
npm run android
npm run ios
```

