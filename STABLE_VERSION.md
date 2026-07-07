# Stable Version

Date: 2026-07-08

Status:
- Windows service runs on local LAN port 8787.
- Android app can discover the desktop service automatically on the same Wi-Fi.
- ZTE Voyage 10 5G is installed and tested.
- Front side mouse button hold starts Doubao voice input through ADB.
- Releasing the front side mouse button stops voice input.
- Voice tap config is calibrated for the ZTE device.

Verified:
- `python -m py_compile mobile_input_server.py`
- Android `assembleDebug`
- APK installed on ZTE device `320617031233`
- Desktop service restarted successfully

Notes:
- `token.txt` is intentionally not tracked.
- `current_url.txt` is generated at service startup and is not tracked.
- Voice input still depends on ADB and `voice_tap_config.json`.
- For a different phone, reinstall the APK and recalibrate ADB device/voice coordinates.
