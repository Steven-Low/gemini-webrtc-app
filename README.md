# Real Open Source WebRTC React Native App with Signalling
Are you frustrated with all those paid api keys or plan? What the hell PipeCat by Daily? (Restrict my plan to 168 hours per month?) I want my super intelligence AI to be slaved 24/7 and no bill!
> Currently, still under heavy development :D

<img src="./public/react-native-webrtc-app.jpeg" />

---

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

### Step 4: Run the sample app

Bingo, it's time to push the launch button.

```js
npm run start
npm run android
npm run ios
```
