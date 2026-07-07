# Mobile Input Sync

This is a local LAN tool. Run the server on the Windows PC, open the URL on your phone, then type on the phone page. Text is synced into the currently focused PC input box.

## Start

Easiest way:

```text
Double-click start_phone_input_sync.bat
```

The script will not start a duplicate service if port `8787` is already running.

Optional startup helpers:

```text
enable_startup.bat
disable_startup.bat
```

`enable_startup.bat` adds a shortcut to the current Windows user's Startup folder, so the desktop service starts automatically after sign-in. `disable_startup.bat` removes that shortcut.

Manual start:

```powershell
cd D:\DAICG_WebAnimation_Studio\DCodex_Projectless\phone_input_sync
python .\mobile_input_server.py
```

The server writes the current phone URL to:

```text
D:\DAICG_WebAnimation_Studio\DCodex_Projectless\phone_input_sync\current_url.txt
```

The access key is saved in `token.txt`, so the URL stays fixed across restarts. You can also bookmark the plain server URL, for example:

```text
http://192.168.20.75:8787/
```

The server will redirect it to the saved-key URL.

## Use

1. Connect the phone and PC to the same Wi-Fi.
2. Open the URL from `current_url.txt` on the phone.
3. Click the target input box on the PC.
4. Type on the phone page.

Inserted text is pasted to the PC automatically. Phone backspace sends Backspace to the PC. The phone keyboard Enter/Send key sends Enter to the PC.

When the PC focus changes, the server notifies the phone page and asks it to focus the typing area. Android browsers may still require one manual tap before they show the keyboard; a native Android app is needed for fully reliable automatic keyboard pop-up.

Auto wake is restricted by `allowed_targets.txt`. By default it only wakes the phone for Codex, ChatGPT/GPT/OpenAI, and Hermes/爱马仕 windows. Add one keyword per line to support more apps later.

## Notes

- The phone page is intentionally blank white except for the text input area.
- During Chinese/Japanese/Korean IME composition, text syncs after the candidate is committed.
- Keep typing at the end of the phone text. Middle-of-text edits are not a good fit for live keyboard mirroring.
- If Windows Firewall asks, allow access on private networks.

## Archive

Old mirror prototype files are archived under:

```text
D:\DAICG_WebAnimation_Studio\DCodex_Projectless\phone_input_sync\archive\mirror_prototype
```

They are not part of the stable phone input workflow.
