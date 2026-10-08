# RailGuard 360 — Combined Project

This combines the two supplied projects into one application.

## What is now shared
- Browser UI: MediaPipe webcam push/fall detection.
- Python `Engine`: shared speed gate, GPS/station lookup, alert cooldown, and ML model.
- Shared `config.json` and `alerts.py`.
- Train number/name and ordered station stops from the supplied 2015 `isl_wise_train_detail_03082015_v1.csv`; mapped stops are shown over OpenStreetMap tiles.
- Original ML/OpenCV camera prototype is still available with `app.py`.

The timetable file is historical (2015) and has station order and distances but no coordinates or rail-track geometry. The app uses OpenStreetMap station search results and draws an approximate straight corridor between stops; this is not an exact track or live train position. Demo-mode train position is simulated along that corridor. In phone mode the blue marker is the phone's GPS position, not train GPS. OpenStreetMap tiles and station lookups require internet access.

## Run the browser version
```bash
pip install -r requirements.txt
python run.py
```
Open `http://localhost:5000` and click **Start camera**. For a phone, deploy the app behind HTTPS, open it in the phone browser, allow camera and location access, start **phone GPS** and the camera, then choose **Add to Home Screen / Install app**. The installed app opens the monitoring screen; `/receiver` opens the recipient dashboard.

### Deploy the server on Render
The project includes [`render.yaml`](./render.yaml) for a Render Blueprint deployment:
1. Put the `RailGuard360_combined` project folder in a Git repository and push it to a Git host. Do not include `.env`, API keys, or other credentials.
2. In Render, create a new **Blueprint** from that repository and select this project's `render.yaml`.
3. Wait for the service build and deployment to finish. Render assigns an HTTPS URL; open `https://<your-service>.onrender.com/api/config` to check that the service responds.
4. In the Render service's environment settings, set credentials for exactly one SMS provider (`FAST2SMS_API_KEY` or the Twilio variables). Without provider credentials the app remains in dry-run mode. Keep secrets only in Render's environment settings, not in Git.
5. Install the APK and enter the assigned HTTPS service URL when prompted. The APK remembers the URL, and you can change it later from its address screen. No rebuild is needed to change the server URL.

The Blueprint requests Render's **Free** web-service plan. Free instances can spin down when idle, causing a long delay on the first request after inactivity; they are suitable for testing, not dependable emergency monitoring. Test using non-emergency recipients before any supervised trial. A successful `/api/config` response verifies the server is reachable; it does not verify SMS delivery. Confirm delivery with the provider and recipient phones.

### Android APK
The Android project is in `android/`. The APK is a native WebView shell around the same web detector: install it, enter the deployed RailGuard HTTPS URL, then grant camera and location permission. Its server address can be changed later in the app. Keep the Python server and SMS gateway reachable; the APK does not include a server or offline SMS delivery. HTTPS is required for camera and location access. No hosted URL was provided, so configure one in the app before monitoring.

The built, debug-signed APK is available as [`RailGuard360.apk`](./RailGuard360.apk). On Android, allow installation from the app used to open the APK, install it, enter the HTTPS RailGuard server URL, and grant camera/location access.

With JDK 17+ and Android SDK Platform 35 plus Build Tools 35.0.0 installed, build a debug APK from PowerShell:
```powershell
cd android
.\gradlew.bat assembleDebug
```
The APK is written to `android/app/build/outputs/apk/debug/app-debug.apk`.

### Phone mode and limitations
- **Live phone GPS** uses the phone's reported coordinates, GPS accuracy, and GPS speed in alerts. Alerts are withheld until a location fix and a reported speed above the configured threshold are available. Browser GPS speed can be unavailable or inaccurate, especially indoors.
- The camera detector analyzes human body poses only (up to four visible people); non-human objects are ignored. Alerts include the same-frame detected-person count. Aim the camera at the area being monitored; this is not a train-mounted sensor integration and cannot reliably detect people outside the camera view.
- Keep the app open while monitoring. Browser background operation, push delivery, cellular coverage, and the configured SMS gateway are not guaranteed.
- **Demo simulator** uses generated train speed and route coordinates for testing. Do not use demo alerts as real incident reports.
- This prototype is not railway-certified, does not control train brakes, and must not replace railway emergency procedures or validated equipment. Test SMS recipients and delivery before any supervised trial.

## Run the original ML camera version
```bash
python app.py
```
Keys: `+` / `-` change speed, `0` restores route speed, `f`/`p` inject events, `q` quits.

## Test the ML pipeline
```bash
python test_pipeline.py
```

## Retrain the model
```bash
python gen_data.py
python train_model.py
```

## SMS
Edit `config.json` to replace placeholder phone numbers. By default alerts are dry-run. For live SMS configure either Fast2SMS or Twilio using `.env` (never commit `.env`).

## Important prototype limitation
The included training data is synthetic and the train GPS is simulated. This is a software prototype, not a safety-certified railway system.
