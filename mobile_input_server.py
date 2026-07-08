from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import weakref
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import uiautomation as auto
except ImportError:
    auto = None


PORT = 8787
APP_DIR = Path(__file__).resolve().parent
TOKEN_FILE = APP_DIR / "token.txt"
ALLOWED_TARGETS_FILE = APP_DIR / "allowed_targets.txt"
VOICE_TAP_CONFIG_FILE = APP_DIR / "voice_tap_config.json"
UPLOAD_DIR = APP_DIR / "uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ADB_PATHS = [
    Path("D:/AndroidBuildTools/android-sdk/platform-tools/adb.exe"),
    Path("adb.exe"),
]
ANDROID_PACKAGE = "com.localinput.sync"
ANDROID_ACTIVITY = "com.localinput.sync/.MainActivity"
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_CONTROL = 0x11
VK_A = 0x41
VK_C = 0x43
VK_V = 0x56
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_LEFT = 0x25
VK_RIGHT = 0x27
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13
CF_HDROP = 15
OP_QUEUE: queue.Queue[dict[str, object]] = queue.Queue()
FOCUS_QUEUES: weakref.WeakSet[queue.Queue[str]] = weakref.WeakSet()
FOCUS_CALLBACK = None
MOUSE_HOOK_CALLBACK = None
MOUSE_HOOK_HANDLE = None
KEYBOARD_HOOK_CALLBACK = None
KEYBOARD_HOOK_HANDLE = None
VOICE_PRESS_LOCK = threading.Lock()
VOICE_PRESS_ACTIVE = False
VOICE_PRESS_ID = 0
VOICE_SYNC_GUARD_UNTIL = 0.0
EVENT_OBJECT_FOCUS = 0x8005
WINEVENT_OUTOFCONTEXT = 0x0000
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_KEYUP = 0x0101
WM_MOUSEWHEEL = 0x020A
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
MSG_WAIT_TIMEOUT_MS = 200
ADB_LAUNCH_INTERVAL = 2.0
AUTO_WAKE_ON_PC_FOCUS = False
PC_SEND_CLEAR_DELAY_MS = 30
SIDE_BUTTON_DOUBLE_TAP_MS = 450
FRONT_SIDE_BUTTON_ID = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOT = 2
CHAT_TARGET_KEYWORDS = ("codex", "gpt", "chatgpt", "openai", "chat.openai", "chat.openai.com", "爱马仕", "hermes")
CHAT_INPUT_NAME_KEYWORDS = (
    "输入",
    "消息",
    "message",
    "prompt",
    "ask",
    "chat",
    "compose",
    "editor",
    "edit",
    "textarea",
    "image",
    "picture",
    "canvas",
    "describe",
    "edit image",
    "图片",
    "图像",
    "编辑",
    "描述",
)
NON_CHAT_INPUT_NAME_KEYWORDS = (
    "地址",
    "搜索",
    "address",
    "search",
    "url",
    "location",
    "omnibox",
)
last_adb_launch = 0.0
PHONE_DRAFT_LOCK = threading.Lock()
PHONE_DRAFT_LENGTH = 0
PHONE_DRAFT_TEXT = ""
PC_TEXT_BEFORE_CLICK: str | None = None
LAST_SIDE_BUTTON_ID = 0
LAST_SIDE_BUTTON_TIME = 0.0


@dataclass(frozen=True)
class WindowContext:
    title: str
    process_path: str

    @property
    def process_name(self) -> str:
        return Path(self.process_path).name


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def load_or_create_token() -> str:
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(12)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


TOKEN = load_or_create_token()


def load_allowed_targets() -> list[str]:
    if not ALLOWED_TARGETS_FILE.exists():
        ALLOWED_TARGETS_FILE.write_text(
            "\n".join(
                [
                    "# One keyword per line. Matches foreground window title, process name, or process path.",
                    "codex",
                    "chatgpt",
                    "gpt",
                    "openai",
                    "爱马仕",
                    "hermes",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    targets = []
    for line in ALLOWED_TARGETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            targets.append(line.casefold())
    return targets


def get_window_text(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_process_path(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_uint(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def get_foreground_context() -> WindowContext:
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]

    hwnd = user32.GetForegroundWindow()
    root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    pid = ctypes.c_uint(0)
    user32.GetWindowThreadProcessId(root_hwnd, ctypes.byref(pid))
    return WindowContext(title=get_window_text(root_hwnd), process_path=get_process_path(pid.value))


def get_focused_control_context_text() -> str:
    if auto is None:
        return ""
    try:
        control = auto.GetFocusedControl()
        parts = []
        current = control
        for _ in range(4):
            if not current:
                break
            parts.extend(
                [
                    str(getattr(current, "Name", "") or ""),
                    str(getattr(current, "AutomationId", "") or ""),
                    str(getattr(current, "ClassName", "") or ""),
                    str(getattr(current, "ControlTypeName", "") or ""),
                ]
            )
            try:
                current = current.GetParentControl()
            except Exception:
                break
        return "\n".join(parts)
    except Exception:
        return ""


def is_allowed_target() -> bool:
    context = get_foreground_context()
    focus_text = get_focused_control_context_text()
    haystack = "\n".join(
        [
            context.title,
            context.process_name,
            context.process_path,
            focus_text,
        ]
    ).casefold()
    return any(target in haystack for target in load_allowed_targets()) or is_gpt_web_context(context, focus_text)


def is_chat_target() -> bool:
    context = get_foreground_context()
    focus_text = get_focused_control_context_text()
    haystack = "\n".join(
        [
            context.title,
            context.process_name,
            context.process_path,
            focus_text,
        ]
    ).casefold()
    return any(keyword.casefold() in haystack for keyword in CHAT_TARGET_KEYWORDS) or is_gpt_web_context(context, focus_text)


def is_gpt_web_context(context: WindowContext, focus_text: str) -> bool:
    process = context.process_name.casefold()
    haystack = "\n".join([context.title, focus_text]).casefold()
    if "prosemirror" not in haystack:
        return False
    has_chat_marker = any(
        marker in haystack
        for marker in (
            "text-token",
            "thread-content",
            "prompt-textarea",
            "composer",
            "edit message",
            "编辑消息",
            "col-start-1",
        )
    )
    if not has_chat_marker:
        return False
    if process in {"msedge.exe", "chrome.exe", "explorer.exe", ""}:
        return True
    return any(browser_name in process for browser_name in ("edge", "chrome"))


def is_probably_chat_input(control: object) -> bool:
    parts = [
        str(getattr(control, "Name", "") or ""),
        str(getattr(control, "AutomationId", "") or ""),
        str(getattr(control, "ClassName", "") or ""),
    ]
    haystack = "\n".join(parts).casefold()
    if any(keyword.casefold() in haystack for keyword in NON_CHAT_INPUT_NAME_KEYWORDS):
        return False
    if not haystack.strip():
        return True
    return any(keyword.casefold() in haystack for keyword in CHAT_INPUT_NAME_KEYWORDS)


def looks_like_non_chat_text(text: str) -> bool:
    stripped = text.strip()
    lowered = stripped.casefold()
    if lowered.startswith(("http://", "https://", "file://", "chrome://", "edge://")):
        return True
    if "://" in lowered and len(stripped) < 300:
        return True
    return False


def get_lan_ip() -> str:
    try:
        command = (
            "Get-NetIPAddress -AddressFamily IPv4 | "
            "Where-Object { $_.IPAddress -notlike '127.*' -and "
            "$_.IPAddress -notlike '169.254.*' -and "
            "$_.InterfaceAlias -notmatch 'vEthernet|VPN|Loopback|Tailscale|ZeroTier' } | "
            "Sort-Object { if ($_.InterfaceAlias -match 'WLAN|Wi-Fi|Ethernet') { 0 } else { 1 } } | "
            "Select-Object -First 1 -ExpandProperty IPAddress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        ip = result.stdout.strip().splitlines()[0].strip()
        if ip:
            return ip
    except (OSError, IndexError, subprocess.SubprocessError):
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def open_clipboard_with_retry(retries: int = 8, delay: float = 0.04) -> None:
    user32 = ctypes.windll.user32
    for attempt in range(retries):
        if user32.OpenClipboard(None):
            return
        if attempt < retries - 1:
            time.sleep(delay)
    raise ctypes.WinError()


def set_clipboard_text(text: str) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    data = (text + "\0").encode("utf-16le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ctypes.WinError()

    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise ctypes.WinError()
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)

    try:
        open_clipboard_with_retry()
    except OSError:
        kernel32.GlobalFree(handle)
        raise
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise ctypes.WinError()
        handle = None
    finally:
        user32.CloseClipboard()


def get_clipboard_text() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    open_clipboard_with_retry()
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return ""
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clipboard_has_text() -> bool:
    user32 = ctypes.windll.user32
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.IsClipboardFormatAvailable.restype = ctypes.c_int
    return bool(user32.IsClipboardFormatAvailable(CF_UNICODETEXT))


def clipboard_has_any_data() -> bool:
    user32 = ctypes.windll.user32
    user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
    user32.EnumClipboardFormats.restype = ctypes.c_uint
    open_clipboard_with_retry()
    try:
        return bool(user32.EnumClipboardFormats(0))
    finally:
        user32.CloseClipboard()


def set_clipboard_file(path: Path) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    file_list = f"{path.resolve()}\0\0".encode("utf-16le")
    dropfiles_size = 20
    data = bytearray(dropfiles_size + len(file_list))
    data[0:4] = dropfiles_size.to_bytes(4, "little")
    data[16:20] = (1).to_bytes(4, "little")
    data[dropfiles_size:] = file_list

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ctypes.WinError()

    locked = kernel32.GlobalLock(handle)
    if not locked:
        kernel32.GlobalFree(handle)
        raise ctypes.WinError()
    ctypes.memmove(locked, bytes(data), len(data))
    kernel32.GlobalUnlock(handle)

    try:
        open_clipboard_with_retry()
    except OSError:
        kernel32.GlobalFree(handle)
        raise
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_HDROP, handle):
            kernel32.GlobalFree(handle)
            raise ctypes.WinError()
        handle = None
    finally:
        user32.CloseClipboard()


def key_event(vk: int, flags: int = 0) -> None:
    ctypes.windll.user32.keybd_event(vk, 0, flags, 0)


def tap_key(vk: int, count: int = 1) -> None:
    for _ in range(max(0, count)):
        key_event(vk)
        key_event(vk, KEYEVENTF_KEYUP)
        time.sleep(0.015)


def send_unicode_text(text: str) -> None:
    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    encoded = text.encode("utf-16le")
    units = [
        int.from_bytes(encoded[index : index + 2], "little")
        for index in range(0, len(encoded), 2)
    ]
    for unit in units:
        inputs = (INPUT * 2)()
        inputs[0].type = 1
        inputs[0].union.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, 0)
        inputs[1].type = 1
        inputs[1].union.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
        sent = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        if sent != 2:
            raise ctypes.WinError()
        time.sleep(0.003)


def should_type_unicode_for_target() -> bool:
    context = get_foreground_context()
    focus_text = get_focused_control_context_text()
    haystack = "\n".join(
        [
            context.title,
            context.process_name,
            context.process_path,
            focus_text,
        ]
    ).casefold()
    return any(keyword in haystack for keyword in ("gpt", "openai", "chat.openai")) or is_gpt_web_context(
        context,
        focus_text,
    )


def log_blocked_voice_target() -> None:
    context = get_foreground_context()
    message = (
        "voice side button blocked: "
        f"title={context.title!r}; process={context.process_name!r}; "
        f"focus={get_focused_control_context_text()[:300]!r}\n"
    )
    (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(message)


def mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
    ctypes.windll.user32.mouse_event(flags, dx, dy, data, 0)


def move_mouse(dx: int, dy: int) -> None:
    mouse_event(MOUSEEVENTF_MOVE, dx, dy)


def left_click() -> None:
    mouse_event(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.025)
    mouse_event(MOUSEEVENTF_LEFTUP)


def left_down() -> None:
    mouse_event(MOUSEEVENTF_LEFTDOWN)


def left_up() -> None:
    mouse_event(MOUSEEVENTF_LEFTUP)


def double_click() -> None:
    left_click()
    time.sleep(0.055)
    left_click()


def right_click() -> None:
    mouse_event(MOUSEEVENTF_RIGHTDOWN)
    time.sleep(0.025)
    mouse_event(MOUSEEVENTF_RIGHTUP)


def scroll_mouse(vertical: int = 0, horizontal: int = 0) -> None:
    if vertical:
        mouse_event(MOUSEEVENTF_WHEEL, data=vertical)
    if horizontal:
        mouse_event(MOUSEEVENTF_HWHEEL, data=horizontal)


def apply_mouse_payload(payload: dict[str, object]) -> None:
    dx = int(float(payload.get("dx", 0) or 0))
    dy = int(float(payload.get("dy", 0) or 0))
    wheel_x = int(float(payload.get("wheelX", 0) or 0))
    wheel_y = int(float(payload.get("wheelY", 0) or 0))
    click = bool(payload.get("click"))
    action = str(payload.get("action", "") or "")
    if dx or dy:
        move_mouse(dx, dy)
    if wheel_x or wheel_y:
        scroll_mouse(vertical=wheel_y, horizontal=wheel_x)
    if action == "doubleClick":
        double_click()
    elif action == "rightClick":
        right_click()
    elif action == "dragStart":
        left_down()
    elif action == "dragEnd":
        left_up()
    elif click or action == "click":
        left_click()


def udp_mouse_worker() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(("0.0.0.0", PORT))
        while True:
            try:
                data, addr = udp.recvfrom(2048)
                payload = json.loads(data.decode("utf-8"))
                if payload.get("discover") == "phone_input_sync":
                    host = get_lan_ip()
                    response = {
                        "ok": True,
                        "name": "phone_input_sync",
                        "host": host,
                        "port": PORT,
                        "base_url": f"http://{host}:{PORT}",
                        "key": TOKEN,
                    }
                    udp.sendto(json.dumps(response).encode("utf-8"), addr)
                    continue
                if payload.get("key") != TOKEN:
                    continue
                apply_mouse_payload(payload)
            except Exception as exc:
                (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"udp mouse failed: {exc!r}\n")


def paste_text(text: str) -> None:
    if not text:
        return
    if should_type_unicode_for_target():
        send_unicode_text(text)
        return
    set_clipboard_text(text)
    time.sleep(0.025)
    key_event(VK_CONTROL)
    key_event(VK_V)
    key_event(VK_V, KEYEVENTF_KEYUP)
    key_event(VK_CONTROL, KEYEVENTF_KEYUP)


def read_focused_input_text() -> str | None:
    if auto is None or not is_chat_target():
        return None
    try:
        with auto.UIAutomationInitializerInThread():
            control = auto.GetFocusedControl()
            control_type = getattr(control, "ControlTypeName", "")
            if control_type not in {"EditControl", "DocumentControl", "TextControl"}:
                return None
            if not is_probably_chat_input(control):
                return None
            control_name = str(getattr(control, "Name", "") or "").strip()

            for method_name in ("GetValuePattern", "GetTextPattern"):
                try:
                    pattern = getattr(control, method_name)()
                except Exception:
                    continue
                try:
                    if method_name == "GetValuePattern":
                        value = pattern.Value
                    else:
                        value = pattern.DocumentRange.GetText(20000)
                except Exception:
                    continue
                if value is not None:
                    text = str(value).rstrip("\r\n")[:20000]
                    if text and text.strip() != control_name and not looks_like_non_chat_text(text):
                        return text
            copied_text = copy_active_input_text()
            if looks_like_non_chat_text(copied_text):
                return None
            return copied_text
    except Exception:
        try:
            if is_chat_target():
                copied_text = copy_active_input_text()
                if not looks_like_non_chat_text(copied_text):
                    return copied_text
        except Exception:
            return None
    return None


def copy_active_input_text() -> str:
    if not is_chat_target():
        return ""
    had_text_clipboard = clipboard_has_text()
    if not had_text_clipboard and clipboard_has_any_data():
        return ""
    previous_clipboard = get_clipboard_text() if had_text_clipboard else ""
    try:
        set_clipboard_text("")
        key_event(VK_CONTROL)
        key_event(VK_A)
        key_event(VK_A, KEYEVENTF_KEYUP)
        time.sleep(0.025)
        key_event(VK_C)
        key_event(VK_C, KEYEVENTF_KEYUP)
    finally:
        key_event(VK_CONTROL, KEYEVENTF_KEYUP)
    time.sleep(0.08)
    try:
        return get_clipboard_text()[:20000]
    finally:
        if had_text_clipboard:
            try:
                set_clipboard_text(previous_clipboard)
            except Exception as exc:
                (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
                    f"restore clipboard failed: {exc!r}\n"
                )
        tap_key(VK_RIGHT)


def paste_file_and_send(path: Path) -> None:
    set_clipboard_file(path)
    time.sleep(0.05)
    key_event(VK_CONTROL)
    key_event(VK_V)
    key_event(VK_V, KEYEVENTF_KEYUP)
    key_event(VK_CONTROL, KEYEVENTF_KEYUP)
    time.sleep(1.2)
    tap_key(VK_RETURN)


def safe_upload_filename(raw_name: str) -> str:
    name = Path(raw_name).name.strip() or "phone_image.jpg"
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in name)
    if "." not in cleaned:
        cleaned += ".jpg"
    return cleaned[:120]


def apply_sync_op(op: dict[str, object]) -> None:
    delete_count = int(op.get("delete", 0) or 0)
    insert_text = str(op.get("insert", "") or "")
    press_enter = bool(op.get("enter"))
    suffix_count = int(op.get("suffix", 0) or 0)

    if suffix_count:
        tap_key(VK_LEFT, suffix_count)
    if delete_count:
        tap_key(VK_BACK, delete_count)
    if insert_text:
        paste_text(insert_text)
    if suffix_count:
        tap_key(VK_RIGHT, suffix_count)
    if press_enter:
        tap_key(VK_RETURN)


def sync_worker() -> None:
    while True:
        op = OP_QUEUE.get()
        try:
            apply_sync_op(op)
        except Exception as exc:
            (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"{exc!r}\n")
        finally:
            OP_QUEUE.task_done()


def broadcast_event(event_name: str) -> None:
    for focus_queue in list(FOCUS_QUEUES):
        try:
            focus_queue.put_nowait(event_name)
        except queue.Full:
            pass


def broadcast_focus() -> None:
    broadcast_event("focus")


def broadcast_voice() -> None:
    # Voice is driven by ADB against the configured device only. Broadcasting it
    # would wake every connected phone app, which is wrong when multiple phones
    # are paired.
    return


def broadcast_clear() -> None:
    mark_phone_draft_cleared()
    broadcast_event("clear")


def diff_text(old_text: str, new_text: str) -> dict[str, object]:
    prefix = 0
    old_len = len(old_text)
    new_len = len(new_text)
    while prefix < old_len and prefix < new_len and old_text[prefix] == new_text[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < old_len - prefix
        and suffix < new_len - prefix
        and old_text[old_len - 1 - suffix] == new_text[new_len - 1 - suffix]
    ):
        suffix += 1
    return {
        "delete": old_len - prefix - suffix,
        "insert": new_text[prefix : new_len - suffix],
        "suffix": suffix,
    }


def update_phone_draft_state(delete_count: int, insert_text: str, press_enter: bool, full_text: str | None = None) -> None:
    global PHONE_DRAFT_LENGTH, PHONE_DRAFT_TEXT
    with PHONE_DRAFT_LOCK:
        if press_enter:
            PHONE_DRAFT_LENGTH = 0
            PHONE_DRAFT_TEXT = ""
            return
        if full_text is not None:
            PHONE_DRAFT_TEXT = full_text
            PHONE_DRAFT_LENGTH = len(full_text)
            return
        PHONE_DRAFT_TEXT = PHONE_DRAFT_TEXT[: max(0, len(PHONE_DRAFT_TEXT) - max(0, delete_count))] + insert_text
        PHONE_DRAFT_LENGTH = len(PHONE_DRAFT_TEXT)


def mark_phone_draft_cleared() -> None:
    global PHONE_DRAFT_LENGTH, PHONE_DRAFT_TEXT
    with PHONE_DRAFT_LOCK:
        PHONE_DRAFT_LENGTH = 0
        PHONE_DRAFT_TEXT = ""


def has_phone_draft() -> bool:
    with PHONE_DRAFT_LOCK:
        return PHONE_DRAFT_LENGTH > 0


def get_phone_draft_length() -> int:
    with PHONE_DRAFT_LOCK:
        return PHONE_DRAFT_LENGTH


def get_phone_draft_text() -> str:
    with PHONE_DRAFT_LOCK:
        return PHONE_DRAFT_TEXT


def is_voice_sync_guard_active() -> bool:
    return time.monotonic() < VOICE_SYNC_GUARD_UNTIL


def should_ignore_voice_full_delete(delete_count: int, insert_text: str, suffix_count: int, press_enter: bool) -> bool:
    if press_enter or insert_text or suffix_count:
        return False
    draft_length = get_phone_draft_length()
    return is_voice_sync_guard_active() and draft_length > 0 and delete_count >= draft_length


def capture_pc_text_before_click() -> None:
    global PC_TEXT_BEFORE_CLICK
    if not is_allowed_target():
        PC_TEXT_BEFORE_CLICK = None
        return
    try:
        PC_TEXT_BEFORE_CLICK = read_focused_input_text()
    except Exception:
        PC_TEXT_BEFORE_CLICK = None


def maybe_clear_phone_after_pc_send() -> None:
    global PC_TEXT_BEFORE_CLICK
    time.sleep(PC_SEND_CLEAR_DELAY_MS / 1000)
    if not is_allowed_target():
        return
    before = PC_TEXT_BEFORE_CLICK
    PC_TEXT_BEFORE_CLICK = None
    if before in (None, "") and not has_phone_draft():
        return
    broadcast_clear()


def clear_phone_after_keyboard_send() -> None:
    time.sleep(PC_SEND_CLEAR_DELAY_MS / 1000)
    if is_allowed_target() and has_phone_draft():
        broadcast_clear()


def load_voice_tap_config() -> dict[str, object]:
    default = {"device_serial": "", "x": 600, "y": 2495, "delay_ms": 250, "hold_ms": 700}
    if not VOICE_TAP_CONFIG_FILE.exists():
        VOICE_TAP_CONFIG_FILE.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default
    try:
        data = json.loads(VOICE_TAP_CONFIG_FILE.read_text(encoding="utf-8"))
        return {
            "device_serial": str(data.get("device_serial", default["device_serial"]) or ""),
            "x": int(data.get("x", default["x"])),
            "y": int(data.get("y", default["y"])),
            "delay_ms": int(data.get("delay_ms", default["delay_ms"])),
            "hold_ms": int(data.get("hold_ms", default["hold_ms"])),
        }
    except Exception as exc:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"voice tap config failed: {exc!r}\n")
        return default


def save_voice_tap_config(config: dict[str, object]) -> dict[str, object]:
    current = load_voice_tap_config()
    merged = {
        "device_serial": str(config.get("device_serial", current["device_serial"]) or ""),
        "x": int(config.get("x", current["x"]) or 0),
        "y": int(config.get("y", current["y"]) or 0),
        "delay_ms": int(config.get("delay_ms", current["delay_ms"]) or 0),
        "hold_ms": int(config.get("hold_ms", current["hold_ms"]) or 1),
    }
    if merged["hold_ms"] < 1:
        merged["hold_ms"] = 1
    VOICE_TAP_CONFIG_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def find_adb() -> str | None:
    for adb_path in ADB_PATHS:
        if adb_path.is_absolute() and adb_path.exists():
            return str(adb_path)
        if not adb_path.is_absolute():
            return str(adb_path)
    return None


def list_adb_devices() -> list[dict[str, str]]:
    adb = find_adb()
    if not adb:
        return []
    try:
        result = subprocess.run(
            [adb, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"adb device list failed: {exc!r}\n")
        return []
    devices: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        meta: dict[str, str] = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                meta[key] = value
        hardware_serial = ""
        if state == "device":
            try:
                serial_result = subprocess.run(
                    [adb, "-s", serial, "shell", "getprop", "ro.serialno"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    check=False,
                )
                hardware_serial = serial_result.stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                hardware_serial = ""
        devices.append(
            {
                "serial": serial,
                "hardware_serial": hardware_serial,
                "state": state,
                "model": meta.get("model", ""),
                "product": meta.get("product", ""),
                "device": meta.get("device", ""),
            }
        )
    return devices


def voice_target_status() -> dict[str, object]:
    config = load_voice_tap_config()
    devices = list_adb_devices()
    target = str(config.get("device_serial", "") or "")
    return {
        "ok": True,
        "config": config,
        "devices": devices,
        "target_connected": any(
            device["state"] == "device" and target in {device["serial"], device.get("hardware_serial", "")}
            for device in devices
        ),
    }


def adb_base_command(adb: str, device_serial: str = "") -> list[str]:
    if device_serial:
        return [adb, "-s", device_serial]
    return [adb]


def resolve_adb_device_serial(adb: str, configured_serial: str) -> str:
    configured_serial = str(configured_serial or "")
    if not configured_serial:
        return ""
    for device in list_adb_devices():
        if device["state"] != "device":
            continue
        if configured_serial in {device["serial"], device.get("hardware_serial", "")}:
            return device["serial"]
    return ""


def is_configured_adb_device_connected(adb: str, device_serial: str) -> bool:
    if not device_serial:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
            "voice target blocked: voice_tap_config.json has no device_serial\n"
        )
        return False
    if resolve_adb_device_serial(adb, device_serial):
        return True
    (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
        f"voice target blocked: configured device {device_serial} is not connected\n"
    )
    return False


def launch_android_app(device_serial: str = "") -> None:
    global last_adb_launch
    now = time.monotonic()
    if now - last_adb_launch < ADB_LAUNCH_INTERVAL:
        return
    last_adb_launch = now
    adb = find_adb()
    if not adb:
        return
    resolved_serial = resolve_adb_device_serial(adb, device_serial) if device_serial else ""
    if device_serial and not resolved_serial:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
            f"adb launch blocked: configured device {device_serial} is not connected\n"
        )
        return
    try:
        subprocess.Popen(
            [
                *adb_base_command(adb, resolved_serial),
                "shell",
                "input",
                "keyevent",
                "KEYCODE_WAKEUP",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        subprocess.Popen(
            [
                *adb_base_command(adb, resolved_serial),
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                ANDROID_ACTIVITY,
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as exc:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"adb launch failed: {exc!r}\n")


def tap_android_voice_button() -> None:
    adb = find_adb()
    if not adb:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("adb not found for voice tap\n")
        return
    config = load_voice_tap_config()
    device_serial = str(config.get("device_serial", "") or "")
    resolved_serial = resolve_adb_device_serial(adb, device_serial)
    if not resolved_serial:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
            f"adb voice tap blocked: configured device {device_serial} is not connected\n"
        )
        return
    try:
        launch_android_app(device_serial)
        time.sleep(max(0, config["delay_ms"]) / 1000)
        subprocess.Popen(
            [
                *adb_base_command(adb, resolved_serial),
                "shell",
                "input",
                "swipe",
                str(config["x"]),
                str(config["y"]),
                str(config["x"]),
                str(config["y"]),
                str(max(1, config["hold_ms"])),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as exc:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"adb voice tap failed: {exc!r}\n")


def send_android_voice_motion(action: str, config: dict[str, object] | None = None) -> None:
    adb = find_adb()
    if not adb:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("adb not found for voice motion\n")
        return
    if config is None:
        config = load_voice_tap_config()
    device_serial = str(config.get("device_serial", "") or "")
    resolved_serial = resolve_adb_device_serial(adb, device_serial)
    if not resolved_serial:
        is_configured_adb_device_connected(adb, device_serial)
        return
    try:
        subprocess.run(
            [
                *adb_base_command(adb, resolved_serial),
                "shell",
                "input",
                "motionevent",
                action,
                str(config["x"]),
                str(config["y"]),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"adb voice motion {action} failed: {exc!r}\n")


def start_android_voice_hold() -> None:
    global VOICE_PRESS_ACTIVE, VOICE_PRESS_ID, VOICE_SYNC_GUARD_UNTIL
    with VOICE_PRESS_LOCK:
        if VOICE_PRESS_ACTIVE:
            return
        VOICE_PRESS_ACTIVE = True
        VOICE_PRESS_ID += 1
        VOICE_SYNC_GUARD_UNTIL = time.monotonic() + 8.0
        press_id = VOICE_PRESS_ID
    config = load_voice_tap_config()
    device_serial = str(config.get("device_serial", "") or "")
    adb = find_adb()
    if not adb:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("adb not found for voice hold\n")
        with VOICE_PRESS_LOCK:
            if press_id == VOICE_PRESS_ID:
                VOICE_PRESS_ACTIVE = False
        return
    if not is_configured_adb_device_connected(adb, device_serial):
        with VOICE_PRESS_LOCK:
            if press_id == VOICE_PRESS_ID:
                VOICE_PRESS_ACTIVE = False
        return
    launch_android_app(device_serial)
    time.sleep(max(0, int(config["delay_ms"])) / 1000)
    with VOICE_PRESS_LOCK:
        if not VOICE_PRESS_ACTIVE or press_id != VOICE_PRESS_ID:
            return
    send_android_voice_motion("DOWN", config)


def stop_android_voice_hold() -> None:
    global VOICE_PRESS_ACTIVE, VOICE_PRESS_ID, VOICE_SYNC_GUARD_UNTIL
    with VOICE_PRESS_LOCK:
        if not VOICE_PRESS_ACTIVE:
            return
        VOICE_PRESS_ACTIVE = False
        VOICE_PRESS_ID += 1
        VOICE_SYNC_GUARD_UNTIL = time.monotonic() + 3.0
    send_android_voice_motion("UP")


def toggle_android_voice_hold() -> None:
    with VOICE_PRESS_LOCK:
        active = VOICE_PRESS_ACTIVE
    if active:
        stop_android_voice_hold()
    else:
        start_android_voice_hold()


def focus_hook_worker() -> None:
    global FOCUS_CALLBACK
    user32 = ctypes.windll.user32
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)

    WinEventProc = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.c_uint,
    )
    last_sent = 0.0
    user32.SetWinEventHook.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        WinEventProc,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    user32.SetWinEventHook.restype = ctypes.c_void_p
    user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]

    def on_focus_event(
        hook: int,
        event: int,
        hwnd: int,
        object_id: int,
        child_id: int,
        event_thread: int,
        event_time: int,
    ) -> None:
        nonlocal last_sent
        now = time.monotonic()
        if now - last_sent < 0.35:
            return
        if not is_allowed_target():
            return
        if not AUTO_WAKE_ON_PC_FOCUS:
            return
        last_sent = now
        broadcast_focus()
        config = load_voice_tap_config()
        device_serial = str(config.get("device_serial", "") or "")
        launch_android_app(device_serial)

    FOCUS_CALLBACK = WinEventProc(on_focus_event)
    hook = user32.SetWinEventHook(
        EVENT_OBJECT_FOCUS,
        EVENT_OBJECT_FOCUS,
        0,
        FOCUS_CALLBACK,
        0,
        0,
        WINEVENT_OUTOFCONTEXT,
    )
    if not hook:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("SetWinEventHook failed\n")
        return

    msg = ctypes.wintypes.MSG()
    try:
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(MSG_WAIT_TIMEOUT_MS / 1000)
    finally:
        user32.UnhookWinEvent(hook)
        ole32.CoUninitialize()


def mouse_side_button_worker() -> None:
    global MOUSE_HOOK_CALLBACK, MOUSE_HOOK_HANDLE
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    LowLevelMouseProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
    last_sent = 0.0

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, ctypes.c_void_p, ctypes.c_uint]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p

    def on_mouse(n_code: int, w_param: int, l_param: int) -> int:
        nonlocal last_sent
        try:
            if n_code >= 0 and int(w_param) == WM_LBUTTONDOWN:
                threading.Thread(target=capture_pc_text_before_click, daemon=True).start()
            elif n_code >= 0 and int(w_param) == WM_LBUTTONUP:
                if is_allowed_target():
                    threading.Thread(target=maybe_clear_phone_after_pc_send, daemon=True).start()
            elif n_code >= 0 and int(w_param) == WM_XBUTTONDOWN:
                now = time.monotonic()
                event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                side_button_id = int(event.mouseData >> 16) & 0xFFFF
                if side_button_id == FRONT_SIDE_BUTTON_ID and now - last_sent >= 0.25:
                    if is_allowed_target():
                        last_sent = now
                        threading.Thread(target=start_android_voice_hold, daemon=True).start()
                        return 1
                    else:
                        last_sent = now
                        threading.Thread(target=log_blocked_voice_target, daemon=True).start()
            elif n_code >= 0 and int(w_param) == WM_XBUTTONUP:
                event = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                side_button_id = int(event.mouseData >> 16) & 0xFFFF
                if side_button_id == FRONT_SIDE_BUTTON_ID:
                    threading.Thread(target=stop_android_voice_hold, daemon=True).start()
                    return 1
        except Exception as exc:
            (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"mouse side button failed: {exc!r}\n")
        return user32.CallNextHookEx(MOUSE_HOOK_HANDLE, n_code, w_param, l_param)

    MOUSE_HOOK_CALLBACK = LowLevelMouseProc(on_mouse)
    module_handle = kernel32.GetModuleHandleW(None)
    MOUSE_HOOK_HANDLE = user32.SetWindowsHookExW(WH_MOUSE_LL, MOUSE_HOOK_CALLBACK, module_handle, 0)
    if not MOUSE_HOOK_HANDLE:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("SetWindowsHookExW mouse failed\n")
        return
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWindowsHookEx(MOUSE_HOOK_HANDLE)


def keyboard_send_worker() -> None:
    global KEYBOARD_HOOK_CALLBACK, KEYBOARD_HOOK_HANDLE
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_int,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )
    last_enter = 0.0

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, ctypes.c_void_p, ctypes.c_uint]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p

    def on_keyboard(n_code: int, w_param: int, l_param: int) -> int:
        nonlocal last_enter
        try:
            if n_code >= 0 and int(w_param) == WM_KEYUP:
                event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if int(event.vkCode) == VK_RETURN:
                    now = time.monotonic()
                    if now - last_enter >= 0.35:
                        last_enter = now
                        threading.Thread(target=clear_phone_after_keyboard_send, daemon=True).start()
        except Exception as exc:
            (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"keyboard send hook failed: {exc!r}\n")
        return user32.CallNextHookEx(KEYBOARD_HOOK_HANDLE, n_code, w_param, l_param)

    KEYBOARD_HOOK_CALLBACK = LowLevelKeyboardProc(on_keyboard)
    module_handle = kernel32.GetModuleHandleW(None)
    KEYBOARD_HOOK_HANDLE = user32.SetWindowsHookExW(WH_KEYBOARD_LL, KEYBOARD_HOOK_CALLBACK, module_handle, 0)
    if not KEYBOARD_HOOK_HANDLE:
        (APP_DIR / "server.err.log").open("a", encoding="utf-8").write("SetWindowsHookExW keyboard failed\n")
        return
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWindowsHookEx(KEYBOARD_HOOK_HANDLE)


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Mobile Input Sync</title>
  <style>
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      background: #fff;
    }
    body {
      overflow: hidden;
    }
    textarea {
      width: 100vw;
      height: 100dvh;
      box-sizing: border-box;
      border: 0;
      outline: 0;
      resize: none;
      padding: 18px;
      background: #fff;
      color: #111;
      font: 22px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    textarea::placeholder {
      color: transparent;
    }
  </style>
</head>
<body>
  <textarea id="text" autofocus autocapitalize="off" autocomplete="off" autocorrect="off" spellcheck="false" enterkeyhint="send"></textarea>
  <script>
    const key = new URLSearchParams(location.search).get("key") || "";
    const text = document.getElementById("text");
    let previous = "";
    let composing = false;
    let pending = Promise.resolve();

    function keepCursorAtEnd() {
      const end = text.value.length;
      try { text.setSelectionRange(end, end); } catch (_) {}
    }

    function wakeKeyboard() {
      try {
        text.focus({ preventScroll: true });
      } catch (_) {
        text.focus();
      }
      keepCursorAtEnd();
    }

    function diff(oldText, newText) {
      let prefix = 0;
      const oldLen = oldText.length;
      const newLen = newText.length;
      while (prefix < oldLen && prefix < newLen && oldText[prefix] === newText[prefix]) {
        prefix++;
      }
      let suffix = 0;
      while (
        suffix < oldLen - prefix &&
        suffix < newLen - prefix &&
        oldText[oldLen - 1 - suffix] === newText[newLen - 1 - suffix]
      ) {
        suffix++;
      }
      return {
        delete: oldLen - prefix - suffix,
        insert: newText.slice(prefix, newLen - suffix),
        suffix
      };
    }

    function post(op) {
      pending = pending.then(() => fetch(`/sync?key=${encodeURIComponent(key)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(op)
      })).catch(() => {});
    }

    function syncNow() {
      if (composing) return;
      const current = text.value;
      const op = diff(previous, current);
      previous = current;
      keepCursorAtEnd();
      if (op.delete || op.insert) post(op);
    }

    text.addEventListener("compositionstart", () => { composing = true; });
    text.addEventListener("compositionend", () => {
      composing = false;
      syncNow();
    });
    text.addEventListener("input", syncNow);
    text.addEventListener("focus", keepCursorAtEnd);
    text.addEventListener("click", keepCursorAtEnd);
    text.addEventListener("beforeinput", (event) => {
      if (event.inputType === "insertLineBreak") {
        event.preventDefault();
        post({ enter: true });
        text.value = "";
        previous = "";
        keepCursorAtEnd();
        return;
      }
      if ((event.inputType === "deleteContentBackward" || event.inputType === "deleteWordBackward") && previous.length === 0) {
        post({ delete: 1 });
      }
    });
    text.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        post({ enter: true });
        text.value = "";
        previous = "";
        keepCursorAtEnd();
        return;
      }
      if (event.key === "Backspace" && previous.length === 0) {
        post({ delete: 1 });
      }
    });
    window.addEventListener("load", () => {
      wakeKeyboard();
    });
    const events = new EventSource(`/events?key=${encodeURIComponent(key)}`);
    events.addEventListener("focus", wakeKeyboard);
  </script>
</body>
</html>"""


CONTROL_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>手机输入助手控制面板</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #f6f7f8;
      color: #111;
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      width: min(920px, calc(100vw - 32px));
      margin: 28px auto;
    }
    h1 {
      margin: 0 0 18px;
      font-size: 24px;
      font-weight: 750;
      letter-spacing: 0;
    }
    .panel {
      background: #fff;
      border: 1px solid #dedede;
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 14px;
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-top: 1px solid #eee;
      padding: 12px 0;
    }
    .row:first-child { border-top: 0; }
    .name { font-weight: 650; }
    .meta { color: #666; font-size: 13px; margin-top: 2px; word-break: break-all; }
    .active {
      color: #087a3a;
      font-weight: 700;
      margin-left: 8px;
    }
    button {
      border: 1px solid #111;
      background: #111;
      color: #fff;
      border-radius: 6px;
      padding: 8px 12px;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary {
      background: #fff;
      color: #111;
      border-color: #c9c9c9;
    }
    button:disabled {
      opacity: .45;
      cursor: default;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    label { display: grid; gap: 5px; color: #444; font-size: 13px; }
    input {
      width: 100%;
      border: 1px solid #cfcfcf;
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      color: #111;
      background: #fff;
    }
    .actions {
      display: flex;
      gap: 10px;
      margin-top: 12px;
      flex-wrap: wrap;
    }
    .status {
      min-height: 22px;
      color: #555;
      margin-top: 10px;
    }
    @media (max-width: 640px) {
      main { width: calc(100vw - 22px); margin: 16px auto; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .row { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <main>
    <h1>手机输入助手控制面板</h1>
    <section class="panel">
      <div class="name">侧键语音目标</div>
      <div class="meta" id="current">读取中...</div>
      <div id="devices"></div>
    </section>
    <section class="panel">
      <div class="name">语音按钮参数</div>
      <div class="meta">不同手机输入法按钮位置不一样。切换手机后，如果按侧键没点到语音键，就调这里。</div>
      <div class="grid" style="margin-top: 12px;">
        <label>X 坐标<input id="x" type="number" inputmode="numeric"></label>
        <label>Y 坐标<input id="y" type="number" inputmode="numeric"></label>
        <label>触发延迟 ms<input id="delay_ms" type="number" inputmode="numeric"></label>
        <label>按住时长 ms<input id="hold_ms" type="number" inputmode="numeric"></label>
      </div>
      <div class="actions">
        <button id="save">保存参数</button>
        <button class="secondary" id="refresh">刷新设备</button>
      </div>
      <div class="status" id="status"></div>
    </section>
  </main>
  <script>
    const key = new URLSearchParams(location.search).get("key") || "";
    const devicesEl = document.getElementById("devices");
    const currentEl = document.getElementById("current");
    const statusEl = document.getElementById("status");
    const fields = ["x", "y", "delay_ms", "hold_ms"].reduce((acc, id) => {
      acc[id] = document.getElementById(id);
      return acc;
    }, {});
    let config = null;

    function setStatus(text) {
      statusEl.textContent = text || "";
    }

    function deviceLabel(device) {
      const model = device.model || device.product || device.device || "Android";
      return `${model} (${device.serial})`;
    }

    async function api(path, options = {}) {
      const join = path.includes("?") ? "&" : "?";
      const response = await fetch(`${path}${join}key=${encodeURIComponent(key)}`, options);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    }

    function render(data) {
      config = data.config;
      for (const id of Object.keys(fields)) fields[id].value = config[id] ?? "";
      const target = config.device_serial || "";
      currentEl.textContent = target
        ? `当前绑定：${target}${data.target_connected ? "，在线" : "，未在线"}`
        : "当前没有绑定手机";
      devicesEl.innerHTML = "";
      if (!data.devices.length) {
        const empty = document.createElement("div");
        empty.className = "meta";
        empty.style.marginTop = "12px";
        empty.textContent = "没有检测到 ADB 手机。请连接数据线并允许 USB 调试。";
        devicesEl.appendChild(empty);
        return;
      }
      for (const device of data.devices) {
        const row = document.createElement("div");
        row.className = "row";
        const left = document.createElement("div");
        const name = document.createElement("div");
        name.className = "name";
        name.textContent = deviceLabel(device);
        if (device.serial === target) {
          const active = document.createElement("span");
          active.className = "active";
          active.textContent = "当前";
          name.appendChild(active);
        }
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = `状态：${device.state}`;
        left.appendChild(name);
        left.appendChild(meta);
        const button = document.createElement("button");
        button.textContent = device.serial === target ? "已选择" : "设为侧键语音";
        button.disabled = device.serial === target || device.state !== "device";
        button.addEventListener("click", () => selectDevice(device.serial));
        row.appendChild(left);
        row.appendChild(button);
        devicesEl.appendChild(row);
      }
    }

    async function refresh() {
      setStatus("正在读取设备...");
      try {
        render(await api("/api/voice-target"));
        setStatus("");
      } catch (error) {
        setStatus(`读取失败：${error.message}`);
      }
    }

    async function selectDevice(serial) {
      setStatus("正在切换...");
      try {
        render(await api("/api/voice-target", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ device_serial: serial })
        }));
        setStatus("已切换侧键语音手机。");
      } catch (error) {
        setStatus(`切换失败：${error.message}`);
      }
    }

    async function saveParams() {
      if (!config) return;
      setStatus("正在保存...");
      const body = { device_serial: config.device_serial || "" };
      for (const id of Object.keys(fields)) body[id] = Number(fields[id].value || 0);
      try {
        render(await api("/api/voice-target", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        }));
        setStatus("参数已保存。");
      } catch (error) {
        setStatus(`保存失败：${error.message}`);
      }
    }

    document.getElementById("refresh").addEventListener("click", refresh);
    document.getElementById("save").addEventListener("click", saveParams);
    refresh();
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def log_message(self, format: str, *args: object) -> None:
        return

    def valid_key(self) -> bool:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        return query.get("key", [""])[0] == TOKEN

    def send_text(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def stream_events(self) -> None:
        focus_queue: queue.Queue[str] = queue.Queue(maxsize=8)
        FOCUS_QUEUES.add(focus_queue)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event_name = focus_queue.get(timeout=20)
                except queue.Empty:
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    continue
                if event_name in {"focus", "voice", "clear"}:
                    if event_name == "voice":
                        continue
                    packet = f"event: {event_name}\ndata: {{}}\n\n".encode("utf-8")
                    self.wfile.write(packet)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/control":
            if not self.valid_key():
                self.send_response(302)
                self.send_header("Location", f"/control?key={urllib.parse.quote(TOKEN)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_text(200, CONTROL_PAGE, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/voice-target":
            if not self.valid_key():
                self.send_text(403, "Forbidden")
                return
            self.send_text(
                200,
                json.dumps(voice_target_status(), ensure_ascii=False),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/snapshot":
            if not self.valid_key():
                self.send_text(403, "Forbidden")
                return
            try:
                text = read_focused_input_text()
            except Exception as exc:
                (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(f"snapshot failed: {exc!r}\n")
                text = None
            self.send_text(
                200,
                json.dumps({"ok": text is not None, "text": text or ""}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/events":
            if not self.valid_key():
                self.send_text(403, "Forbidden")
                return
            self.stream_events()
            return
        if parsed.path != "/":
            self.send_text(404, "Not Found")
            return
        if not self.valid_key():
            self.send_response(302)
            self.send_header("Location", f"/?key={urllib.parse.quote(TOKEN)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_text(200, PAGE, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/voice-target" and self.valid_key():
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            current = load_voice_tap_config()
            update = {
                "device_serial": str(payload.get("device_serial", current["device_serial"]) or ""),
                "x": payload.get("x", current["x"]),
                "y": payload.get("y", current["y"]),
                "delay_ms": payload.get("delay_ms", current["delay_ms"]),
                "hold_ms": payload.get("hold_ms", current["hold_ms"]),
            }
            save_voice_tap_config(update)
            self.send_text(
                200,
                json.dumps(voice_target_status(), ensure_ascii=False),
                "application/json; charset=utf-8",
            )
            return

        if parsed.path == "/mouse" and self.valid_key():
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            apply_mouse_payload(payload)
            self.send_text(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return

        if parsed.path == "/upload" and self.valid_key():
            query = urllib.parse.parse_qs(parsed.query)
            filename = safe_upload_filename(query.get("filename", ["phone_image.jpg"])[0])
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                self.send_text(400, "Empty upload")
                return
            if length > MAX_UPLOAD_BYTES:
                self.send_text(413, "Upload too large")
                return
            UPLOAD_DIR.mkdir(exist_ok=True)
            target = UPLOAD_DIR / f"{int(time.time() * 1000)}_{filename}"
            remaining = length
            with target.open("wb") as out:
                while remaining > 0:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            paste_file_and_send(target)
            self.send_text(
                200,
                json.dumps({"ok": True, "path": str(target)}),
                "application/json; charset=utf-8",
            )
            return

        if parsed.path != "/sync" or not self.valid_key():
            self.send_text(403, "Forbidden")
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        delete_count = int(payload.get("delete", 0) or 0)
        insert_text = str(payload.get("insert", "") or "")
        suffix_count = int(payload.get("suffix", 0) or 0)
        press_enter = bool(payload.get("enter"))
        full_text = str(payload.get("text")) if "text" in payload else None
        if full_text is not None and not press_enter:
            previous_text = get_phone_draft_text()
            op = diff_text(previous_text, full_text)
            delete_count = int(op["delete"])
            insert_text = str(op["insert"])
            suffix_count = int(op["suffix"])
        if should_ignore_voice_full_delete(delete_count, insert_text, suffix_count, press_enter):
            (APP_DIR / "server.err.log").open("a", encoding="utf-8").write(
                f"ignored transient voice full delete: delete={delete_count}\n"
            )
            self.send_text(200, json.dumps({"ok": True, "ignored": True}), "application/json; charset=utf-8")
            return
        update_phone_draft_state(delete_count, insert_text, press_enter, full_text)
        OP_QUEUE.put(
            {
                "delete": delete_count,
                "insert": insert_text,
                "suffix": suffix_count,
                "enter": press_enter,
            }
        )
        self.send_text(200, json.dumps({"ok": True}), "application/json; charset=utf-8")


def main() -> int:
    if sys.platform != "win32":
        print("This helper currently supports Windows only.", flush=True)
        return 1

    threading.Thread(target=sync_worker, daemon=True).start()
    threading.Thread(target=focus_hook_worker, daemon=True).start()
    threading.Thread(target=mouse_side_button_worker, daemon=True).start()
    threading.Thread(target=keyboard_send_worker, daemon=True).start()
    threading.Thread(target=udp_mouse_worker, daemon=True).start()
    ip = get_lan_ip()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    url = f"http://{ip}:{PORT}/?key={urllib.parse.quote(TOKEN)}"
    (APP_DIR / "current_url.txt").write_text(url, encoding="utf-8")
    print("Mobile input sync is running.", flush=True)
    print(url, flush=True)
    print("Click the target input box on the PC first, then type on the phone page.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
