# 🕷️ Spidey App — one client for every screen

A Flutter client for Spidey: the same chat, approvals and voice, on **iOS, Android,
macOS, Windows and Linux**. It speaks the exact WebSocket protocol of `spidey serve`
(`spidey/server/app.py`), so anything the web UI can do over `/ws`, this app can too.

## Build it

Platform runners are committed — with the
[Flutter SDK](https://docs.flutter.dev/get-started/install) installed it's just:

```bash
cd app
flutter pub get
flutter run                      # picks a connected device/desktop
flutter build apk                # Android
flutter build macos              # macOS, etc.
```

Verified: `flutter analyze` is clean and the release build compiles and boots
(web target; it connects to the server and correctly walks the auth flow).

Two platform permissions to add before shipping voice:

- **iOS** (`ios/Runner/Info.plist`): `NSMicrophoneUsageDescription` and
  `NSSpeechRecognitionUsageDescription` (any short string).
- **Android** (`android/app/src/main/AndroidManifest.xml`):
  `<uses-permission android:name="android.permission.RECORD_AUDIO"/>` and
  `INTERNET`.
- **macOS**: enable *Audio Input* + *Outgoing Connections* in the entitlements files.

## Where the brain runs (the honest offline matrix)

The app is a client; the agent (and the model) run wherever `spidey serve` runs:

| Your device | Fully offline setup |
|---|---|
| **Windows / macOS / Linux PC** | Run `spidey serve` + Ollama **on the same machine**, point the app at `http://127.0.0.1:8000`. 100% offline. |
| **Android phone** | Best: point the app at your PC on the same Wi-Fi (`http://<pc-ip>:8000`) — offline in the sense that nothing leaves your network. Adventurous: Ollama inside Termux runs small models (≤3B) fully on-phone. |
| **iPhone / iPad** | Point the app at a Mac/PC on your LAN. iOS doesn't allow a background shell-capable server on-device. |

Voice is on-device on every platform: speech-to-text uses the OS speech engine
(`speech_to_text`, with `onDevice: true`), and replies are spoken with the OS's local
voices (`flutter_tts`). Hands-free **"Hey Spidey"** wake word is currently a web-UI
feature (the browser streams mic audio to the local Vosk recognizer); on mobile it's
tap-to-talk — OS rules make always-on mic listening a poor citizen there anyway.

> ⚠️ Same warning as the Dockerfile: `spidey serve` has **no authentication**. Bind it
> to localhost or your trusted LAN only — never the public internet.
