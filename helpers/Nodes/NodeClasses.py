"""
NodeClasses.py — per-node widgets and capture helpers.

Installed onto Node by Nodes.py at import time.  Once installed, any
node can call:

    self.add_button("text", on_click=fn)
    self.add_line_edit(socket_name="Value")
    self.add_slider(0, 100, socket_name="Steps")
    self.attach(any_qwidget, anchor=ANCHOR_HEADER)
    self.capture_click("x", "y")
    self.capture_hotkey("*args")
    self.capture_press("*args")

And per-template subclasses registered here get instantiated by
build_node_from_template when a spec carries node_class = <tag>.
"""

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QGraphicsProxyWidget, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QLabel, QSlider, QSpinBox, QDoubleSpinBox, QPlainTextEdit,
    QProgressBar, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QMessageBox, QApplication,
    QListWidget, QListWidgetItem, QScrollArea, QFrame,
    QFileDialog, QSystemTrayIcon,
)


# ---------------------------------------------------------------- #
#  System notification helper                                       #
# ---------------------------------------------------------------- #

_NOTIFY_ICON = None


def _system_notify(title, message, ms=3500):
    """Show a tray notification.  Silent no-op on headless systems."""
    global _NOTIFY_ICON
    try:
        app = QApplication.instance()
        if app is None:
            return
        if _NOTIFY_ICON is None:
            # QSystemTrayIcon refuses to show messages without an
            # icon on most desktops, and prints "No Icon set" if none
            # is provided.  A 22x22 swatch of the accent colour is
            # enough to silence that and give the notification a face.
            from PyQt5.QtGui import QPixmap, QIcon, QColor
            pm = QPixmap(22, 22)
            pm.fill(QColor("#E08C4A"))
            _NOTIFY_ICON = QSystemTrayIcon(QIcon(pm))
            _NOTIFY_ICON.setToolTip("PyTorchUI")
            _NOTIFY_ICON.setVisible(True)
        _NOTIFY_ICON.showMessage(
            str(title), str(message),
            QSystemTrayIcon.Information, int(ms))
    except Exception as ex:
        print("[notify] %s" % ex)


# Anchors
ANCHOR_HEADER  = "header"
ANCHOR_ROW     = "row"
ANCHOR_SECTION = "section"
ANCHOR_SOCKET  = "socket"
ANCHOR_FOOTER  = "footer"
ANCHOR_FREE    = "free"


# Registry filled by the factories at the bottom of this file.
_NODE_CLASS_REGISTRY = {}

# Concrete subclasses built by install(), keyed by tag.
LIVE_NODE_CLASSES = {}


def register_node_class(name):
    def _wrap(factory):
        _NODE_CLASS_REGISTRY[name] = factory
        return factory
    return _wrap


def get_node_class(name):
    return _NODE_CLASS_REGISTRY.get(name)


# ---------------------------------------------------------------- #
#  Styles                                                           #
# ---------------------------------------------------------------- #

_BTN_STYLE = (
    "QPushButton{background:#3C3C3C;border:1px solid #666;"
    "border-radius:3px;color:#EEE;font-size:10px;padding:2px 6px;}"
    "QPushButton:hover{background:#4A4A4A;border:1px solid #E08C4A;}"
)
_EDIT_STYLE = (
    "QLineEdit{background:#3C3C3C;border:1px solid #555;border-radius:3px;"
    "color:#EEE;font-size:10px;padding:2px 4px;}"
    "QLineEdit:focus{border:1px solid #E08C4A;}"
)


# ---------------------------------------------------------------- #
#  Capture overlays                                                 #
# ---------------------------------------------------------------- #

# ------------------------------------------------------------------ #
#  Xlib-based global pointer query                                   #
# ------------------------------------------------------------------ #
#
# Two layers of detection:
#
#   1. XInput2 raw events.  Delivered to every client that selected
#      them, regardless of which window the pointer is over or what
#      grabs are currently held.  This is the primary path.  It
#      catches clicks on panels, docks, and any other window that
#      would otherwise consume a button grab.
#
#   2. XQueryPointer polling.  Kept as a fallback for X servers
#      without XInput2 (very old, or XWayland builds that do not
#      advertise it).  Polling cannot see clicks shorter than the
#      poll interval, and can miss clicks while another client holds
#      a grab, but it works for most cases.

_XLIB_DISPLAY = None
_XLIB_TRIED   = False


def _xlib_pointer():
    """Return (x, y, pressed) using XQueryPointer, or None on failure."""
    global _XLIB_DISPLAY, _XLIB_TRIED
    if not _XLIB_TRIED:
        _XLIB_TRIED = True
        try:
            from Xlib import display as _xd
            _XLIB_DISPLAY = _xd.Display()
        except Exception as ex:
            _XLIB_DISPLAY = False
            print("[capture] Xlib unavailable (%s); using Qt-only detection"
                  % ex)
    if _XLIB_DISPLAY is False or _XLIB_DISPLAY is None:
        return None
    try:
        root = _XLIB_DISPLAY.screen().root
        q = root.query_pointer()
        mask = (1 << 8) | (1 << 9) | (1 << 10)  # Button1|2|3
        return (int(q.root_x), int(q.root_y), bool(q.mask & mask))
    except Exception:
        return None


# ---- XInput2 raw-event listener ------------------------------------ #

_XI2_STATE = {"available": None, "display": None, "callbacks": []}


def _xi2_start():
    """Start the XInput2 raw-event listener exactly once.

    Returns True if the listener is running.  The listener thread
    blocks on d.next_event() and dispatches RawButtonPress events to
    every callable in _XI2_STATE["callbacks"].
    """
    if _XI2_STATE["available"] is not None:
        return _XI2_STATE["available"]
    try:
        import threading
        from Xlib import display as _xd
        from Xlib.ext import xinput as _xi

        d = _xd.Display()
        # python-xlib has changed xinput_query_version's signature
        # between releases.  Try the current form first, then the
        # legacy one, then just proceed without a version check.
        ver = None
        try:
            ver = d.xinput_query_version(2, 0)
        except TypeError:
            try:
                ver = d.xinput_query_version()
            except Exception:
                ver = None
        except Exception as ex:
            _XI2_STATE["available"] = False
            print("[capture] XInput2 unavailable (%s); using XQueryPointer"
                  % ex)
            return False
        if ver is not None:
            major = getattr(ver, "major_version", 2)
            minor = getattr(ver, "minor_version", 0)
            if (major, minor) < (2, 0):
                _XI2_STATE["available"] = False
                print("[capture] XInput2 version %d.%d is too old; "
                      "using XQueryPointer" % (major, minor))
                return False

        root = d.screen().root
        mask = _xi.RawButtonPressMask | _xi.RawButtonReleaseMask
        root.xi_select_events([(0, mask)])   # 0 = all master devices
        d.sync()

        _XI2_STATE["display"] = d
        _XI2_STATE["available"] = True

        # python-xlib exposes the raw event code as a module attribute
        # in newer versions and as a plain integer in older ones.
        RAW_PRESS = getattr(_xi, "RawButtonPress", 15)

        def _loop():
            while True:
                try:
                    ev = d.next_event()
                except Exception:
                    return
                if getattr(ev, "evtype", None) != RAW_PRESS:
                    continue
                detail = int(getattr(ev, "detail", 0))
                if detail < 1 or detail > 9:
                    continue
                try:
                    p = root.query_pointer()
                    x, y = int(p.root_x), int(p.root_y)
                except Exception:
                    continue
                for cb in list(_XI2_STATE["callbacks"]):
                    try:
                        cb(x, y, detail)
                    except TypeError:
                        try:
                            cb(x, y)
                        except Exception:
                            pass
                    except Exception as ex:
                        print("[capture] xi2 callback:", ex)

        threading.Thread(target=_loop, daemon=True,
                         name="pytorchui-xi2").start()
        print("[capture] using XInput2 raw events for global click detection")
        return True
    except Exception as ex:
        _XI2_STATE["available"] = False
        print("[capture] XInput2 init failed (%s); using XQueryPointer" % ex)
        return False


_BUTTON_NAMES = {
    1: "left", 2: "middle", 3: "right",
    4: "scroll_up", 5: "scroll_down",
    6: "scroll_left", 7: "scroll_right",
    8: "back", 9: "forward",
}


class CaptureOverlay(QWidget):
    def __init__(self, passthrough=True, on_click=None, buttons=None):
        super().__init__(
            None,
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.X11BypassWindowManagerHint)
        self._passthrough = bool(passthrough)
        self._on_click = on_click
        self._buttons = set(buttons) if buttons is not None else {"left"}
        self._finished = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowOpacity(0.15)
        self.setStyleSheet("background:#101010;")

        # Span every attached screen.  primaryScreen().virtualGeometry()
        # only covers the virtual desktop the primary screen belongs
        # to, which on some multi-head setups excludes panels and
        # docks that live on a different monitor.
        try:
            screens = QApplication.screens()
        except Exception:
            screens = []
        if screens:
            geo = screens[0].geometry()
            for scr in screens[1:]:
                geo = geo.united(scr.geometry())
        else:
            geo = QApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        print("[capture] overlay covering %s" % (geo.getRect(),))

        self._prev_buttons = Qt.NoButton
        self._prev_pressed = False
        self._poll = None

        # Start (or join) the XInput2 listener.  If it is running,
        # register our click handler with it.
        if _xi2_start():
            _XI2_STATE["callbacks"].append(self._on_xi2_click)

        if self._passthrough:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._poll = QTimer(self)
            self._poll.setInterval(8)
            self._poll.timeout.connect(self._poll_mouse)
        else:
            self.setCursor(Qt.CrossCursor)

    # ---- XInput2 entry point (called from the listener thread) ---- #

    def _on_xi2_click(self, x, y, button=1):
        name = _BUTTON_NAMES.get(button)
        if name is None or name not in self._buttons:
            return
        QTimer.singleShot(0, lambda: self._finish(x, y, name))

    # ---- lifecycle ---- #

    def start(self):
        self.show()
        self.raise_()
        # Do NOT call activateWindow(): stealing keyboard focus from
        # a panel that is about to be clicked makes the panel hide,
        # which is exactly the case we are trying to support.
        print("[capture] overlay shown: visible=%s rect=%s"
              % (self.isVisible(), self.geometry().getRect()))
        if self._poll is not None:
            self._prev_buttons = QApplication.mouseButtons()
            p = _xlib_pointer()
            if p is not None:
                self._prev_pressed = p[2]
            self._poll.start()

    def _poll_mouse(self):
        if "left" not in self._buttons:
            return
        p = _xlib_pointer()
        if p is None:
            return
        x, y, pressed = p
        if pressed and not self._prev_pressed:
            self._prev_pressed = True
            print("[capture] Xlib click at (%d, %d)" % (x, y))
            self._finish(x, y, "left")
            return
        self._prev_pressed = pressed

    def mousePressEvent(self, event):
        if self._passthrough:
            event.ignore()
            return
        p = event.globalPos()
        print("[capture] overlay received click at (%d, %d)" % (p.x(), p.y()))
        self._finish(p.x(), p.y())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            print("[capture] cancelled by Escape")
            self._finish_cancel()

    # ---- finish helpers ---- #

    def _teardown(self):
        if self._poll is not None:
            try:
                self._poll.stop()
            except Exception:
                pass
        try:
            _XI2_STATE["callbacks"].remove(self._on_xi2_click)
        except (ValueError, KeyError):
            pass
        try:
            self.close()
        except Exception:
            pass

    def _finish(self, x, y, button="left"):
        if self._finished:
            return
        self._finished = True
        self._teardown()
        if self._on_click:
            try:
                try:
                    self._on_click(int(x), int(y), button)
                except TypeError:
                    self._on_click(int(x), int(y))
            except Exception as ex:
                print("[capture] on_click raised:", ex)

    def _finish_cancel(self):
        if self._finished:
            return
        self._finished = True
        self._teardown()




#  Keyboard capture  --  evdev (Linux) + WH_KEYBOARD_LL (Windows)  #
# ------------------------------------------------------------------ #

import sys as _kgsys
import os as _kos
import struct as _kstruct
from PyQt5.QtCore import QObject as _QObject, pyqtSignal as _pyqtSignal

# ---- evdev key code -> name mapping (partial, common keys) ---- #
_EVDEV_KEYS = {
    1: "esc", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6",
    8: "7", 9: "8", 10: "9", 11: "0", 12: "-", 13: "=",
    14: "backspace", 15: "tab", 16: "q", 17: "w", 18: "e",
    19: "r", 20: "t", 21: "y", 22: "u", 23: "i", 24: "o",
    25: "p", 26: "[", 27: "]", 28: "enter", 29: "ctrl",
    30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h",
    36: "j", 37: "k", 38: "l", 39: ";", 40: "'", 41: "`",
    42: "shift", 43: "\\", 44: "z", 45: "x", 46: "c",
    47: "v", 48: "b", 49: "n", 50: "m", 51: ",", 52: ".",
    53: "/", 54: "shift", 55: "*", 56: "alt", 57: "space",
    58: "capslock", 59: "f1", 60: "f2", 61: "f3", 62: "f4",
    63: "f5", 64: "f6", 65: "f7", 66: "f8", 67: "f9",
    68: "f10", 69: "numlock", 70: "scrolllock", 87: "f11",
    88: "f12", 96: "enter", 97: "ctrl", 98: "/",
    99: "printscreen", 100: "alt", 102: "home", 103: "up",
    104: "pageup", 105: "left", 106: "right", 107: "end",
    108: "down", 109: "pagedown", 110: "insert", 111: "delete",
    113: "mute", 114: "volumedown", 115: "volumeup",
    116: "power", 119: "pause", 125: "win", 126: "win", 127: "menu",
    128: "stop", 142: "sleep", 150: "www", 152: "calculator",
    158: "back", 159: "forward", 161: "eject", 163: "nextsong",
    164: "playpause", 165: "prevsong", 172: "homepage",
    173: "refresh", 183: "f13", 184: "f14", 185: "f15",
    186: "f16", 187: "f17", 188: "f18", 189: "f19",
    190: "f20", 191: "f21", 192: "f22", 193: "f23",
    194: "f24", 217: "search", 224: "brightnessdown",
    225: "brightnessup",
}

# ---- Windows VK -> name mapping (partial, common keys) ---- #
_VK_TO_NAME = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc",
    0x20: "space", 0x21: "pageup", 0x22: "pagedown", 0x23: "end",
    0x24: "home", 0x25: "left", 0x26: "up", 0x27: "right",
    0x28: "down", 0x2C: "printscreen", 0x2D: "insert", 0x2E: "delete",
    0x5B: "win", 0x5C: "win", 0x10: "shift", 0x11: "ctrl",
    0x12: "alt", 0xA0: "shift", 0xA1: "shift", 0xA2: "ctrl",
    0xA3: "ctrl", 0xA4: "alt", 0xA5: "alt",
}
for _i in range(0x30, 0x3A): _VK_TO_NAME[_i] = chr(_i)
for _i in range(0x41, 0x5B): _VK_TO_NAME[_i] = chr(_i).lower()
for _i in range(0x70, 0x88): _VK_TO_NAME[_i] = "f%d" % (_i - 0x6F)


class _KeyGrabber(_QObject):
    '''Keyboard capture, using evdev on Linux and a hook on Windows.'''
    key_pressed  = _pyqtSignal(str)
    key_released = _pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._evdev_fds = []
        self._win_hook = None
        self._win_cb = None
        self._win_queue = []
        self._win_poll = None

    def start(self, exclusive=True):
        if _kgsys.platform == "win32":
            return self._start_win(exclusive=exclusive)
        return self._start_evdev(exclusive=exclusive)

    def stop(self):
        if self._backend == "evdev":
            self._stop_evdev()
        elif self._backend == "win":
            self._stop_win()
        self._backend = None

    # ---- Linux (evdev) ---- #
    EVIOCGRAB = 0x40044590           # _IOW('E', 0x90, int)

    def _start_evdev(self, exclusive=True):
        import glob, fcntl
        devices = sorted(glob.glob("/dev/input/event*"))
        if not devices:
            return False

        key_a_byte, key_a_bit = 30 // 8, 1 << (30 % 8)
        opened = []
        for path in devices:
            fd = -1
            # EVIOCGRAB requires a writable fd.  Try R/W first, fall
            # back to R/O only when we do NOT need to grab.
            order = (_kos.O_RDWR | _kos.O_NONBLOCK,
                     _kos.O_RDONLY | _kos.O_NONBLOCK)
            for flags in order:
                try:
                    fd = _kos.open(path, flags)
                    break
                except PermissionError:
                    continue
                except OSError:
                    continue
            if fd < 0:
                continue
            try:
                buf = fcntl.ioctl(fd, 0x80604521, bytes(96))  # EVIOCGBIT_KEY
                if not (buf[key_a_byte] & key_a_bit):
                    _kos.close(fd)
                    continue
            except Exception:
                _kos.close(fd)
                continue
            opened.append((path, fd))

        if not opened:
            return False

        # ---- exclusive grab (only when asked) ---- #
        grabbed = 0
        if exclusive:
            arg_on = _kstruct.pack("I", 1)
            for _p, fd in opened:
                try:
                    fcntl.ioctl(fd, self.EVIOCGRAB, arg_on)
                    grabbed += 1
                except Exception:
                    pass

        self._evdev_fds = opened
        self._evdev_grabbed = grabbed > 0
        self._backend = "evdev"

        self._evdev_timer = QTimer(self)
        self._evdev_timer.setInterval(10)
        self._evdev_timer.timeout.connect(self._read_evdev)
        self._evdev_timer.start()

        if exclusive and grabbed == 0:
            print("[keygrab] evdev: %d device(s), 0 grabbed — "
                  "EVIOCGRAB was refused.  The OS will ALSO act on "
                  "the keys.  Try running with sudo, or check that "
                  "you are in the 'input' group." % len(opened))
        else:
            print("[keygrab] evdev: %d device(s), %d grabbed (%s)"
                  % (len(opened), grabbed,
                     "exclusive" if grabbed else "observe-only"))
        return True

    def _read_evdev(self):
        import select
        EV_KEY = 1
        ev_size = _kstruct.calcsize("llHHi")
        for _p, fd in self._evdev_fds:
            while True:
                try:
                    r, _, _ = select.select([fd], [], [], 0)
                    if not r: break
                    data = _kos.read(fd, ev_size)
                    if len(data) < ev_size: break
                    _, _, etype, code, value = _kstruct.unpack("llHHi", data)
                    if etype == EV_KEY and code in _EVDEV_KEYS:
                        name = _EVDEV_KEYS[code]
                        if value == 1: self.key_pressed.emit(name)
                        elif value == 0: self.key_released.emit(name)
                except (BlockingIOError, OSError):
                    break

    def _stop_evdev(self):
        import fcntl
        if hasattr(self, '_evdev_timer'):
            self._evdev_timer.stop()
        arg_off = _kstruct.pack("I", 0)
        for _p, fd in self._evdev_fds:
            if getattr(self, "_evdev_grabbed", False):
                try:
                    fcntl.ioctl(fd, self.EVIOCGRAB, arg_off)
                except Exception:
                    pass
            try:
                _kos.close(fd)
            except Exception:
                pass
        self._evdev_fds = []
        self._evdev_grabbed = False
        print("[keygrab] evdev: released")

    # ---- Windows ---- #
    def _start_win(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._win_user32 = user32

        WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x100, 0x104

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        state = self
        def _hook(nCode, wParam, lParam):
            try:
                if nCode == 0:
                    info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        state._win_queue.append(info.vkCode)
                        return 1 # Swallow key
            except Exception: pass
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._win_cb = HOOKPROC(_hook)
        h = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._win_cb, kernel32.GetModuleHandleW(None), 0)
        if not h:
            print("[keygrab] SetWindowsHookExW failed"); self._win_cb = None; return False
        self._win_hook = h
        self._backend = "win"
        self._win_poll = QTimer(self)
        self._win_poll.setInterval(15)
        self._win_poll.timeout.connect(self._poll_win)
        self._win_poll.start()
        print("[keygrab] WH_KEYBOARD_LL hook installed")
        return True

    def _poll_win(self):
        while self._win_queue:
            vk = self._win_queue.pop(0)
            name = _VK_TO_NAME.get(vk)
            if name: self.key_pressed.emit(name)

    def _stop_win(self):
        if self._win_poll: self._win_poll.stop()
        try:
            if self._win_hook and self._win_user32:
                self._win_user32.UnhookWindowsHookEx(self._win_hook)
                print("[keygrab] WH_KEYBOARD_LL hook released")
        except Exception: pass
        finally: self._win_hook, self._win_cb = None, None


class KeyCaptureDialog(QDialog):
    '''Records a key combination from raw OS events.'''
    _MODS = ("ctrl", "shift", "alt", "win")

    def __init__(self, parent=None, multi=True, exclusive=True):
        super().__init__(parent)
        self.setWindowTitle("Capture hotkey" if multi else "Capture key")
        self.setModal(True)
        self.setMinimumSize(380, 150)
        self.result_keys = None
        self._multi = multi
        self._exclusive = bool(exclusive)
        self._mods_down = []

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        msg = QLabel("Press the combination now." if multi else "Press a single key.")
        msg.setAlignment(Qt.AlignCenter); msg.setStyleSheet("color:#DDD;font-size:12px;")
        v.addWidget(msg)
        self.preview = QLabel("\u2014"); self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("color:#E08C4A;font-size:18px;font-weight:bold;padding:8px;")
        v.addWidget(self.preview)

        self._grabber = _KeyGrabber(self)
        self._grabber.key_pressed.connect(self._on_press)
        self._grabber.key_released.connect(self._on_release)

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(
            0, lambda: self._grabber.start(exclusive=self._exclusive))

    def done(self, result):
        self._grabber.stop()
        super().done(result)

    def _refresh_preview(self):
        parts = list(self._mods_down)
        self.preview.setText(" + ".join(parts) if parts else "\u2014")

    def _on_press(self, name):
        if name == "esc":
            self.reject(); return

        if name in self._MODS:
            if name not in self._mods_down:
                self._mods_down.append(name)
            self._refresh_preview()
            return

        # A non-modifier key was pressed.
        if self._multi:
            # Hotkey mode: include currently held modifiers.
            self.result_keys = list(self._mods_down) + [name]
        else:
            # Press mode: just the key itself.
            self.result_keys = [name]

        self.preview.setText(" + ".join(self.result_keys))
        QTimer.singleShot(120, self.accept)

    def _on_release(self, name):
        if name in self._mods_down:
            self._mods_down.remove(name)
        self._refresh_preview()

class _NodeWidgetHost:

    def attach(self, widget, anchor=ANCHOR_ROW, h=None, w=None,
               key=None, side="right", x=0, y=0):
        if not hasattr(self, "_attached_widgets"):
            self._attached_widgets = []
        if h is None:
            h = widget.minimumHeight() or widget.sizeHint().height() or 22
        if w is None:
            w = 0   # 0 = stretch to node width
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        proxy.setZValue(6)
        rec = {"widget": widget, "proxy": proxy, "anchor": anchor,
               "h": int(h), "w": int(w), "key": key, "side": side,
               "x": float(x), "y": float(y)}
        self._attached_widgets.append(rec)
        self.layout()
        return widget

    def detach(self, widget):
        for rec in list(getattr(self, "_attached_widgets", [])):
            if rec["widget"] is widget:
                try:
                    rec["proxy"].setParentItem(None)
                    rec["proxy"].deleteLater()
                except Exception:
                    pass
                self._attached_widgets.remove(rec)
                self.layout()
                return True
        return False

    # -------- convenience wrappers -------- #

    def add_button(self, text, on_click=None, tooltip=None, style=None,
                   anchor=ANCHOR_ROW, h=22, w=None, key=None, side="right",
                   x=0, y=0):
        b = QPushButton(text)
        b.setStyleSheet(style or _BTN_STYLE)
        b.setMinimumHeight(h)
        if tooltip:
            b.setToolTip(tooltip)
        if on_click:
            b.clicked.connect(lambda _c=False: on_click())
        return self.attach(b, anchor=anchor, h=h, w=w, key=key,
                           side=side, x=x, y=y)

    def add_line_edit(self, text="", placeholder=None, socket_name=None,
                      anchor=ANCHOR_ROW, h=22, w=None, key=None,
                      side="right", x=0, y=0):
        le = QLineEdit(str(text))
        le.setStyleSheet(_EDIT_STYLE)
        le.setMinimumHeight(h)
        if placeholder:
            le.setPlaceholderText(placeholder)
        self.attach(le, anchor=anchor, h=h, w=w, key=key,
                    side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                le, "textChanged", socket_name,
                transform=lambda t: repr(str(t)))
        return le

    def add_checkbox(self, label, checked=False, socket_name=None,
                     anchor=ANCHOR_ROW, h=20, key=None, side="right",
                     x=0, y=0):
        cb = QCheckBox(str(label))
        cb.setChecked(bool(checked))
        cb.setMinimumHeight(h)
        self.attach(cb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                cb, "toggled", socket_name,
                transform=lambda b: repr(bool(b)))
        return cb

    def add_combo(self, items, current=0, socket_name=None,
                  anchor=ANCHOR_ROW, h=22, key=None, side="right",
                  x=0, y=0):
        cb = QComboBox()
        cb.addItems([str(x) for x in items])
        if 0 <= current < len(items):
            cb.setCurrentIndex(current)
        cb.setMinimumHeight(h)
        self.attach(cb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                cb, "currentTextChanged", socket_name,
                transform=lambda t: repr(str(t)))
        return cb

    def add_label(self, text, anchor=ANCHOR_ROW, h=18, key=None,
                  side="right", x=0, y=0, style=None):
        lb = QLabel(str(text))
        lb.setStyleSheet(style or "color:#DDD;font-size:10px;")
        lb.setMinimumHeight(h)
        return self.attach(lb, anchor=anchor, h=h, key=key,
                           side=side, x=x, y=y)

    def add_slider(self, minimum=0, maximum=100, value=0,
                   socket_name=None, anchor=ANCHOR_ROW, h=22,
                   key=None, side="right", x=0, y=0):
        s = QSlider(Qt.Horizontal)
        s.setRange(int(minimum), int(maximum))
        s.setValue(int(value))
        s.setMinimumHeight(h)
        self.attach(s, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                s, "valueChanged", socket_name,
                transform=lambda v: repr(int(v)))
        return s

    def add_spin(self, value=0, minimum=-10**9, maximum=10**9,
                 socket_name=None, anchor=ANCHOR_ROW, h=22, key=None,
                 side="right", x=0, y=0):
        sb = QSpinBox()
        sb.setRange(int(minimum), int(maximum))
        sb.setValue(int(value))
        sb.setMinimumHeight(h)
        self.attach(sb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                sb, "valueChanged", socket_name,
                transform=lambda v: repr(int(v)))
        return sb

    def add_dspin(self, value=0.0, minimum=-1e12, maximum=1e12,
                  socket_name=None, anchor=ANCHOR_ROW, h=22, key=None,
                  side="right", x=0, y=0):
        sb = QDoubleSpinBox()
        sb.setRange(float(minimum), float(maximum))
        sb.setValue(float(value))
        sb.setMinimumHeight(h)
        self.attach(sb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                sb, "valueChanged", socket_name,
                transform=lambda v: repr(float(v)))
        return sb

    def add_progress(self, anchor=ANCHOR_ROW, h=14, key=None):
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(0)
        pb.setTextVisible(False)
        pb.setMinimumHeight(h)
        return self.attach(pb, anchor=anchor, h=h, key=key)

    def add_text_edit(self, text="", anchor=ANCHOR_ROW, h=60, key=None):
        te = QPlainTextEdit()
        te.setPlainText(str(text))
        te.setMinimumHeight(h)
        return self.attach(te, anchor=anchor, h=h, key=key)

    # -------- signal <-> socket binding -------- #

    def bind_widget_to_socket(self, widget, signal_name, socket_name,
                              is_input=True, transform=None):
        sock = self.socket(socket_name, is_input=is_input)
        if sock is None:
            print("[bind] no socket named %r" % socket_name)
            return False

        def _on_signal(*args):
            if transform is not None:
                try:
                    v = transform(*args)
                except Exception as ex:
                    print("[bind] transform:", ex); return
            else:
                v = args[0] if args else None
            if v is None:
                return
            if hasattr(sock, "set_value"):
                sock.set_value(v)
            else:
                sock.value = v
            self.update()

        try:
            getattr(widget, signal_name).connect(_on_signal)
        except Exception as ex:
            print("[bind]", signal_name, ex)
            return False
        return True

    # -------- capture helpers -------- #

# -------- ask for keyboard capture -------- #

    def _ask_keyboard_capture(self, kind):
        """Return True (also replay), False (record only), or None (cancel).

        kind is "hotkey" or "press" — used only in the wording.
        """
        try:
            box = QMessageBox(self._view_window())
            box.setWindowTitle("Capture %s" % kind)
            box.setText("The next key combination will be recorded.")
            box.setInformativeText(
                "Should the combination also be replayed once after\n"
                "recording, so you can check you captured the right keys?\n"
                "\n"
                "Yes — record the combination, then fire it once via\n"
                "      pyautogui.  Useful for verifying the capture.\n"
                "No  — record the combination and do nothing else.")
            yes    = box.addButton("Yes (test it)",     QMessageBox.YesRole)
            no     = box.addButton("No (capture only)", QMessageBox.NoRole)
            cancel = box.addButton("Cancel",            QMessageBox.RejectRole)
            box.setDefaultButton(no)
            box.exec_()
            btn = box.clickedButton()
            if btn is None or btn is cancel:
                return None
            return btn is yes
        except Exception as ex:
            print("[capture_%s] ask failed: %s" % (kind, ex))
            return False

    def capture_click(self, x_socket="x", y_socket="y"):
        try:
            box = QMessageBox(self._view_window())
            box.setWindowTitle("Capture click")
            box.setText("The next click will be recorded.")
            box.setInformativeText(
                "Should the operating system also receive that click?\n\n"
                "Yes — click reaches the window under the cursor, "
                "AND is recorded here.\n"
                "No  — click is recorded here and swallowed.")
            yes    = box.addButton("Yes (passthrough)", QMessageBox.YesRole)
            no     = box.addButton("No (capture only)",  QMessageBox.NoRole)
            cancel = box.addButton("Cancel",              QMessageBox.RejectRole)
            box.setDefaultButton(yes)
            box.exec_()
            btn = box.clickedButton()
            if btn is None or btn is cancel:
                return
            passthrough = (btn is yes)
        except Exception as ex:
            print("[capture_click] ask:", ex)
            passthrough = True

        fdlg = ClickEventFilterDialog(self._view_window())
        if fdlg.exec_() != fdlg.Accepted:
            return
        buttons = fdlg.selected()
        if not buttons:
            return

        def _done(x, y, button="left"):
            print("[capture_click] got (%r, %r) button=%s"
                  % (x, y, button))
            xs = self.socket(x_socket, is_input=True)
            ys = self.socket(y_socket, is_input=True)
            if xs is not None:
                vx = str(int(x))
                if hasattr(xs, "set_value"): xs.set_value(vx)
                else: xs.value = vx
            if ys is not None:
                vy = str(int(y))
                if hasattr(ys, "set_value"): ys.set_value(vy)
                else: ys.value = vy
            bs = self.socket("button", is_input=True)
            if bs is not None:
                bs.set_value(repr(button))
            self.update()

        overlay = CaptureOverlay(passthrough=passthrough,
                                 on_click=_done,
                                 buttons=buttons)
        overlay.start()
        self._capture_overlay = overlay

    def capture_hotkey(self, target_socket="*args", multi=True):
        replay = self._ask_keyboard_capture("hotkey")
        if replay is None:
            print("[capture_hotkey] cancelled at ask step")
            return
        # "Yes (test it)" -> record AND let the OS see the keys,
        #                   then replay once via pyautogui.
        # "No  (capture only)" -> record only, grab the device so
        #                   the OS never sees the keys at all.
        dlg = KeyCaptureDialog(self._view_window(),
                               multi=multi,
                               exclusive=(not replay))
        r = dlg.exec_()
        print("[capture_hotkey] exec_ returned %r, keys=%r exclusive=%r"
              % (r, dlg.result_keys, not replay))
        if r != dlg.Accepted or not dlg.result_keys:
            print("[capture_hotkey] cancelled or empty")
            return
        sock = self.socket(target_socket, is_input=True)
        print("[capture_hotkey] socket %r -> %r"
              % (target_socket, sock))
        if sock is None:
            print("[capture_hotkey] available inputs:",
                  [s.name for s in self.inputs])
            return
        v = repr(list(dlg.result_keys))
        if hasattr(sock, "set_value"): sock.set_value(v)
        else: sock.value = v
        print("[capture_hotkey] wrote socket =", v)
        self.update()
        if replay:
            keys = list(dlg.result_keys)
            QTimer.singleShot(220, lambda: self._replay_hotkey(keys))

    def _replay_hotkey(self, keys):
        try:
            import pyautogui
            print("[capture_hotkey] replaying", keys)
            pyautogui.hotkey(*keys)
        except Exception as ex:
            print("[capture_hotkey] replay failed:", ex)

    def capture_press(self, target_socket="*args"):
        replay = self._ask_keyboard_capture("press")
        if replay is None:
            print("[capture_press] cancelled at ask step")
            return
        dlg = KeyCaptureDialog(self._view_window(),
                               multi=False,
                               exclusive=(not replay))
        r = dlg.exec_()
        print("[capture_press] exec_ returned %r, keys=%r exclusive=%r"
              % (r, dlg.result_keys, not replay))
        if r != dlg.Accepted or not dlg.result_keys:
            print("[capture_press] cancelled or empty")
            return
        sock = self.socket(target_socket, is_input=True)
        print("[capture_press] socket %r -> %r"
              % (target_socket, sock))
        if sock is None:
            print("[capture_press] available inputs:",
                  [s.name for s in self.inputs])
            return
        v = repr(list(dlg.result_keys))
        if hasattr(sock, "set_value"): sock.set_value(v)
        else: sock.value = v
        print("[capture_press] wrote socket =", v)
        self.update()
        if replay:
            keys = list(dlg.result_keys)
            QTimer.singleShot(220, lambda: self._replay_press(keys))

    def _replay_press(self, keys):
        try:
            import pyautogui
            key = keys[-1] if keys else None
            if key is None:
                return
            print("[capture_press] replaying", key)
            pyautogui.press(key)
        except Exception as ex:
            print("[capture_press] replay failed:", ex)

    # -------- layout -------- #

    def layout_custom(self):
        recs = getattr(self, "_attached_widgets", None)
        if not recs:
            return
        row_y = 36
        for rec in recs:
            self._place_widget(rec, row_y)
            if rec["anchor"] == ANCHOR_ROW:
                row_y += rec["h"] + 4

    def _place_widget(self, rec, row_y):
        proxy = rec["proxy"]
        nw = self.width
        if rec["anchor"] == ANCHOR_HEADER:
            w = rec["w"] or 84
            x, y = nw - w - 6, (28 - rec["h"]) / 2.0
        elif rec["anchor"] == ANCHOR_ROW:
            w = rec["w"] or (nw - 16)
            x, y = (nw - w) / 2.0, row_y
        elif rec["anchor"] == ANCHOR_SECTION:
            sec = None
            for s in self.sections:
                if s["name"] == rec["key"]:
                    sec = s; break
            if sec is None or sec["rect"].isNull():
                return
            w = rec["w"] or (nw - 16)
            rows = max(len(sec["inputs"]), len(sec["outputs"]))
            x = (nw - w) / 2.0
            y = sec["rect"].bottom() + rows * 22 + 2
        elif rec["anchor"] == ANCHOR_SOCKET:
            is_in = (rec["side"] == "left")
            sock = self.socket(rec["key"], is_input=is_in)
            if sock is None:
                return
            w = rec["w"] or 84
            x = 16 if rec["side"] == "left" else (nw - w - 16)
            y = sock.y() - rec["h"] / 2.0
        elif rec["anchor"] == ANCHOR_FOOTER:
            w = rec["w"] or (nw - 16)
            x = (nw - w) / 2.0
            out = getattr(self, "_output_rect", None)
            y = (out.top() - rec["h"] - 4) if out is not None else row_y
        elif rec["anchor"] == ANCHOR_FREE:
            w = rec["w"] or 84
            x, y = rec["x"], rec["y"]
        else:
            return
        try:
            proxy.setPos(x, y)
            proxy.resize(w if w > 0 else (nw - 16), rec["h"])
        except Exception:
            pass

    def _widgets_reserved_height(self):
        total = 0
        for rec in getattr(self, "_attached_widgets", []):
            if rec["anchor"] in (ANCHOR_ROW, ANCHOR_SECTION, ANCHOR_FOOTER):
                total += rec["h"] + 4
        return (total + 4) if total else 0

    def after_template_built(self, template):
        pass

    # -------- file browser -------- #

    def _open_file_browser(self, path_socket="Path",
                           save=False, filt="All Files (*)"):
        from PyQt5.QtWidgets import QFileDialog
        sock = self.socket(path_socket, is_input=True)
        if sock is None:
            print("[file_button] no socket named %r" % path_socket)
            return
        start = ""
        try:
            cur = sock.value
            if isinstance(cur, str) and cur:
                start = cur.strip("'\"")
        except Exception:
            pass
        if save:
            path, _ = QFileDialog.getSaveFileName(
                self._view_window(), "Save file", start, filt)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self._view_window(), "Open file", start, filt)
        if not path:
            return
        if hasattr(sock, "set_value"):
            sock.set_value(repr(path))
        else:
            sock.value = repr(path)
        print("[file_button] wrote %s -> %s" % (path_socket, path))
        self.update()

    # -------- multi capture -------- #

    def _open_multi_capture(self, kind,
                            target_socket="*args",
                            x_socket="x", y_socket="y"):
        # Same ask as single capture.  For clicks the choice only
        # matters for what happens to stray key presses during the
        # recording; for press / hotkey it decides whether the OS
        # sees the keys you record.
        try:
            box = QMessageBox(self._view_window())
            box.setWindowTitle("Multi-capture %s" % kind)
            box.setText(
                "Record a sequence of %s actions." % kind)
            box.setInformativeText(
                "Should the operating system also receive the "
                "%s you do?\n\n"
                "Yes — actions reach the window under the cursor, "
                "and are recorded here too.\n"
                "No  — actions are recorded here and swallowed "
                "(keys only; mouse clicks still reach the OS).\n\n"
                "Either way, press ESC three times in a row to stop."
                % kind)
            yes    = box.addButton("Yes (passthrough)", QMessageBox.YesRole)
            no     = box.addButton("No (capture only)", QMessageBox.NoRole)
            cancel = box.addButton("Cancel", QMessageBox.RejectRole)
            box.setDefaultButton(yes)
            box.exec_()
            btn = box.clickedButton()
            if btn is None or btn is cancel:
                return
            exclusive = (btn is no)
        except Exception as ex:
            print("[multi] ask failed:", ex)
            exclusive = True

        if kind == "click":
            fdlg = ClickEventFilterDialog(self._view_window())
        else:
            fdlg = KeyEventFilterDialog(self._view_window(), kind=kind)
        if fdlg.exec_() != fdlg.Accepted:
            return
        cats = fdlg.selected()
        if not cats:
            return

        dlg = MultiCaptureDialog(self._view_window(),
                                 kind=kind,
                                 exclusive=exclusive,
                                 categories=cats)
        if dlg.exec_() != dlg.Accepted:
            return
        selected = dlg.selected_items()
        print("[multi] %d item(s) selected of %d"
              % (len(selected), len(dlg._items)))
        if not selected:
            return

        try:
            chain = bool(dlg.chk_chain.isChecked())
        except Exception:
            chain = True

        if chain and len(selected) >= 1:
            self._apply_multi_chain(kind, selected,
                                    target_socket, x_socket, y_socket)
        else:
            self._set_single_multi_value(
                kind, [it["value"] for it in selected],
                target_socket, x_socket, y_socket)
        self.update()

    # ---------- combined-in-one-node writer ---------- #

    def _set_single_multi_value(self, kind, values,
                                target_socket, x_socket, y_socket):
        if kind == "click":
            xs = [str(int(v[0])) for v in values]
            ys = [str(int(v[1])) for v in values]
            sx = self.socket(x_socket, is_input=True)
            sy = self.socket(y_socket, is_input=True)
            if sx is not None:
                sx.set_value(repr(xs))
            if sy is not None:
                sy.set_value(repr(ys))
            print("[multi] wrote x=%r y=%r" % (xs, ys))
        elif kind == "hotkey":
            sock = self.socket(target_socket, is_input=True)
            if sock is not None:
                sock.set_value(repr([list(v) for v in values]))
                print("[multi] wrote %s = %r"
                      % (target_socket, [list(v) for v in values]))
        else:  # press
            sock = self.socket(target_socket, is_input=True)
            if sock is not None:
                sock.set_value(repr(list(values)))
                print("[multi] wrote %s = %r"
                      % (target_socket, list(values)))

    # ---------- per-node writer for the chain ---------- #

    def _set_one_value(self, node, kind, value,
                       target_socket, x_socket, y_socket):
        if kind == "click":
            x, y = value
            sx = node.socket(x_socket, is_input=True)
            sy = node.socket(y_socket, is_input=True)
            if sx is not None:
                sx.set_value(str(int(x)))
            if sy is not None:
                sy.set_value(str(int(y)))
        elif kind == "hotkey":
            sock = node.socket(target_socket, is_input=True)
            if sock is not None:
                sock.set_value(repr(list(value)))
        else:  # press
            sock = node.socket(target_socket, is_input=True)
            if sock is not None:
                sock.set_value(repr([value]))

    # ---------- chain builder ---------- #

    def _apply_multi_chain(self, kind, selected,
                           target_socket, x_socket, y_socket):
        scene = self.scene()
        if scene is None:
            return
        try:
            from helpers.Nodes.Nodes import find_template
        except ImportError:
            try:
                from Nodes import find_template
            except ImportError:
                print("[multi] find_template unavailable")
                return

        tpl_name = self.metadata.get("template") or self.title
        tpl = find_template(tpl_name)
        if tpl is None:
            print("[multi] template %r not registered" % tpl_name)
            return

        # First item -> current node.
        self._set_one_value(self, kind, selected[0]["value"],
                            target_socket, x_socket, y_socket)

        # Remaining items -> new chain nodes, positioned below.
        base_x = self.pos().x()
        base_y = self.pos().y() + self.height + 40
        prev = self
        created = []
        for i, item in enumerate(selected[1:], start=1):
            try:
                dup = scene.add_node_from_template(
                    tpl, QPointF(base_x, base_y))
            except Exception as ex:
                print("[multi] create node failed:", ex)
                break
            if dup is None:
                continue
            try:
                dup.layout()
            except Exception:
                pass
            self._set_one_value(dup, kind, item["value"],
                                target_socket, x_socket, y_socket)

            # Wire Path Out -> Path In (or Next -> Prev for Start/End).
            connected = False
            try:
                src = prev.socket("Path Out", is_input=False)
                dst = dup.socket("Path In", is_input=True)
                if src is None:
                    src = prev.socket("Next", is_input=False)
                if dst is None:
                    dst = dup.socket("Prev", is_input=True)
                if src is not None and dst is not None:
                    scene.connect_sockets(src, dst)
                    connected = True
            except Exception as ex:
                print("[multi] connect failed:", ex)
            if not connected:
                print("[multi] could not wire %s -> %s"
                      % (prev.title, dup.title))

            created.append(dup)
            prev = dup
            base_y += dup.height + 40

        print("[multi] chained %d node(s)" % (len(created) + 1))
        try:
            scene.graph_changed.emit()
        except Exception:
            pass

    def _show_preview_button(self):
        """Open the full preview dialog for the payload on this node."""
        win = self._view_window()
        if win is None:
            return
        info = getattr(self, "_preview_info", None) or {}
        if not info:
            try:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(
                    win, "No preview yet",
                    "Run the pipeline (F5) first.  This node "
                    "populates as soon as its Source produces media.")
            except Exception:
                pass
            return
        kind = info.get("kind", "")
        nid = self.metadata.get("id") or self.title
        try:
            if kind in ("image", "plot"):
                path = info.get("path", "")
                if path and os.path.isfile(path):
                    win._show_image_dialog(nid, path)
                else:
                    print("[preview] no image file at", path)
            elif kind in ("audio", "video"):
                path = info.get("path", "")
                if path and os.path.isfile(path):
                    win._show_media_player(nid, path, kind)
            elif kind == "folder":
                win._show_folder_dialog(nid, info)
            elif kind == "table":
                win._show_table_dialog(nid, info)
            elif kind in ("text", "json"):
                win._show_text_dialog(nid, info, mono=True)
            elif kind in ("html", "markdown"):
                win._show_html_dialog(nid, info)
            else:
                print("[preview] unknown kind:", kind)
        except Exception as ex:
            print("[preview] show failed:", ex)


    def _view_window(self):
        try:
            v = self.scene().views()
            if v:
                return v[0].window()
        except Exception:
            pass
        return None


class _MultiClickOverlay(QWidget):
    """Transparent full-screen overlay that reports every click
    until stop() is called."""

    def __init__(self, on_click, parent=None, buttons=None):
        super().__init__(
            None,
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.X11BypassWindowManagerHint)
        self._on_click = on_click
        self._buttons = set(buttons) if buttons is not None else {"left"}
        self._finished = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowOpacity(0.12)
        self.setStyleSheet("background:#101010;")

        try:
            screens = QApplication.screens()
        except Exception:
            screens = []
        if screens:
            geo = screens[0].geometry()
            for scr in screens[1:]:
                geo = geo.united(scr.geometry())
        else:
            geo = QApplication.primaryScreen().geometry()
        self.setGeometry(geo)

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._prev_pressed = False
        self._poll = QTimer(self)
        self._poll.setInterval(8)
        self._poll.timeout.connect(self._poll_mouse)
        if _xi2_start():
            _XI2_STATE["callbacks"].append(self._on_xi2)

    def start(self):
        self.show()
        self.raise_()
        p = _xlib_pointer()
        if p is not None:
            self._prev_pressed = p[2]
        self._poll.start()
        print("[multi] overlay shown, rect=%s" % (self.geometry().getRect(),))

    def _on_xi2(self, x, y, button=1):
        name = _BUTTON_NAMES.get(button)
        if name is None or name not in self._buttons:
            return
        QTimer.singleShot(0, lambda: self._emit(x, y, name))

    def _poll_mouse(self):
        if "left" not in self._buttons:
            return
        p = _xlib_pointer()
        if p is None:
            return
        x, y, pressed = p
        if pressed and not self._prev_pressed:
            self._prev_pressed = True
            self._emit(x, y, "left")
            return
        self._prev_pressed = pressed

    def _emit(self, x, y, button="left"):
        if self._finished:
            return
        try:
            try:
                self._on_click(int(x), int(y), button)
            except TypeError:
                self._on_click(int(x), int(y))
        except Exception as ex:
            print("[multi] on_click:", ex)

    def stop(self):
        if self._finished:
            return
        self._finished = True
        try: self._poll.stop()
        except Exception: pass
        try:
            _XI2_STATE["callbacks"].remove(self._on_xi2)
        except (ValueError, KeyError):
            pass
        try: self.close()
        except Exception: pass


class MultiCaptureDialog(QDialog):
    """Records a sequence of user actions, then lets the user pick
    which ones to keep.  ESC three times in a row stops recording."""

    ESC_TO_STOP = 3

    def __init__(self, parent=None, kind="click",
                 exclusive=True, categories=None):
        super().__init__(parent)
        self._kind = kind
        self._exclusive = bool(exclusive)
        self._categories = set(categories) if categories else None
        self._items = []
        self._esc_count = 0
        self._recording = True
        self._overlay = None
        self._grabber = None
        self._pending = []

        self.setWindowTitle("Multi-capture %s" % kind)
        self.setModal(True)
        self.resize(640, 560)

        from PyQt5.QtWidgets import QListWidget, QListWidgetItem
        self._QListWidget = QListWidget
        self._QListWidgetItem = QListWidgetItem

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self.lbl_status = QLabel("Recording...")
        self.lbl_status.setStyleSheet(
            "font-size:14px;font-weight:bold;color:#E08C4A;")
        v.addWidget(self.lbl_status)

        self.lbl_hint = QLabel(
            "Press ESC %d times in a row to stop recording."
            % self.ESC_TO_STOP)
        self.lbl_hint.setStyleSheet("color:#999;")
        v.addWidget(self.lbl_hint)

        frow = QHBoxLayout()
        frow.addWidget(QLabel("Filter:"))
        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("search captured items...")
        frow.addWidget(self.edit_filter, 1)
        v.addLayout(frow)

        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Range:"))
        self.edit_range = QLineEdit()
        self.edit_range.setPlaceholderText(
            "e.g. 1-4,7,8   or   full   or   1,5,7,9")
        rrow.addWidget(self.edit_range, 1)
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._apply_range)
        rrow.addWidget(btn_apply)
        v.addLayout(rrow)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setStyleSheet(
            "QListWidget{background:#1E1E1E;color:#DDD;"
            "border:1px solid #333;padding:4px;}"
            "QListWidget::item{padding:3px 4px;}"
            "QListWidget::item:hover{background:#2A2A2A;}")
        v.addWidget(self.list, 1)

        chain_row = QHBoxLayout()
        self.chk_chain = QCheckBox(
            "Create a separate node for each item "
            "(otherwise keep them all in this node as a list)")
        self.chk_chain.setChecked(True)
        chain_row.addWidget(self.chk_chain)
        v.addLayout(chain_row)

        arow = QHBoxLayout()
        for text, fn in (
            ("All",    lambda: self._set_all(True)),
            ("None",   lambda: self._set_all(False)),
            ("Invert", self._invert),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            arow.addWidget(b)
        arow.addStretch(1)
        b_clear = QPushButton("Clear & Re-record")
        b_clear.clicked.connect(self._clear_and_restart)
        arow.addWidget(b_clear)
        b_stop = QPushButton("Stop Now")
        b_stop.clicked.connect(self._stop_recording)
        arow.addWidget(b_stop)
        v.addLayout(arow)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        b_ok = QPushButton("OK")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        bottom.addWidget(b_cancel)
        bottom.addWidget(b_ok)
        v.addLayout(bottom)

        self.edit_filter.textChanged.connect(self._apply_filter)
        QTimer.singleShot(0, self._start_recording)

    def _start_recording(self):
        self._recording = True
        self._esc_count = 0
        self._pending = []
        self.lbl_status.setText("Recording...")
        _system_notify(
            "Multi-capture %s" % self._kind,
            "Press ESC %d times in a row to stop."
            % self.ESC_TO_STOP,
            4000)

        # Grabber always runs: for clicks it is the only way to see
        # ESC at all (the click overlay is transparent to the mouse
        # but not to the keyboard, and QDialog would otherwise close
        # on the first ESC).  For clicks we grab in observe-only
        # mode so surrounding apps keep working; for key capture we
        # respect the user's choice from the ask dialog.
        self._grabber = _KeyGrabber(self)
        self._grabber.key_pressed.connect(self._on_key_press)
        exclusive = self._exclusive if self._kind != "click" else False
        try:
            self._grabber.start(exclusive=exclusive)
        except TypeError:
            self._grabber.start()

        if self._kind == "click":
            self._overlay = _MultiClickOverlay(on_click=self._add_click)
            self._overlay.start()

    # Qt would close the dialog on the first ESC.  Swallow it, so
    # the ESC x3 counter in _on_key_press is what actually stops us.
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyReleaseEvent(event)

    def reject(self):
        # Only the explicit Cancel button may reject.  Escape is
        # routed through the counter instead.
        if not self._recording:
            super().reject()

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        if self._overlay is not None:
            try: self._overlay.stop()
            except Exception: pass
            self._overlay = None
        if self._grabber is not None:
            try: self._grabber.stop()
            except Exception: pass
            self._grabber = None
        n = len(self._items)
        self.lbl_status.setText(
            "Stopped.  %d item(s) captured.  Pick the ones to keep." % n)
        self.lbl_hint.setText(
            "Check items below, or type a range like 1-4,7,8 or full.")
        self._refresh_list()

    def _clear_and_restart(self):
        if self._overlay is not None:
            try: self._overlay.stop()
            except Exception: pass
            self._overlay = None
        if self._grabber is not None:
            try: self._grabber.stop()
            except Exception: pass
            self._grabber = None
        self._items = []
        self._refresh_list()
        QTimer.singleShot(60, self._start_recording)

    def done(self, result):
        if self._overlay is not None:
            try: self._overlay.stop()
            except Exception: pass
        if self._grabber is not None:
            try: self._grabber.stop()
            except Exception: pass
        super().done(result)

    def _add_click(self, x, y, button="left"):
        if not self._recording:
            return
        if self._categories is not None \
                and button not in self._categories:
            return
        self._items.append({
            "label": "%s (%d, %d)" % (button, x, y),
            "value": (x, y, button),
        })
        self._refresh_list()
        self.lbl_status.setText(
            "Recording...  %d captured" % len(self._items))

    def _on_key_press(self, name):
        if not self._recording:
            return

        # Category filter (never filter ESC - it is the stop key).
        if name != "esc" and self._categories is not None \
                and self._kind != "click":
            if _classify_key(name) not in self._categories:
                return
        if name == "esc":
            self._esc_count += 1
            if self._esc_count >= self.ESC_TO_STOP:
                self._stop_recording()
                return
            self.lbl_hint.setText(
                "Press ESC %d more time(s) to stop."
                % (self.ESC_TO_STOP - self._esc_count))
            return
        self._esc_count = 0
        self.lbl_hint.setText(
            "Press ESC %d times in a row to stop recording."
            % self.ESC_TO_STOP)
        if self._kind == "hotkey" and name in ("ctrl", "shift", "alt", "win"):
            if name not in self._pending:
                self._pending.append(name)
            return
        if self._kind == "hotkey":
            combo = list(self._pending) + [name]
            self._pending = []
            self._items.append({
                "label": "hotkey  " + " + ".join(combo),
                "value": combo,
            })
        else:
            self._items.append({
                "label": "key  %s" % name,
                "value": name,
            })
        self._refresh_list()
        self.lbl_status.setText(
            "Recording...  %d captured" % len(self._items))

    def _refresh_list(self):
        self.list.clear()
        for i, it in enumerate(self._items):
            li = self._QListWidgetItem("%d.  %s" % (i + 1, it["label"]))
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Checked)
            li.setData(Qt.UserRole, i)
            self.list.addItem(li)
        self._apply_filter(self.edit_filter.text())

    def _apply_filter(self, text):
        text = (text or "").strip().lower()
        for i in range(self.list.count()):
            li = self.list.item(i)
            li.setHidden(bool(text) and text not in li.text().lower())

    def _apply_range(self):
        spec = self.edit_range.text().strip().lower()
        if not spec:
            return
        if spec == "full":
            self._set_all(True)
            return
        keep = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    a, b = int(a.strip()), int(b.strip())
                    for n in range(min(a, b), max(a, b) + 1):
                        keep.add(n - 1)
                except Exception:
                    pass
            else:
                try:
                    keep.add(int(part) - 1)
                except Exception:
                    pass
        for i in range(self.list.count()):
            li = self.list.item(i)
            idx = li.data(Qt.UserRole)
            li.setCheckState(Qt.Checked if idx in keep else Qt.Unchecked)

    def _set_all(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(
                Qt.Checked if on else Qt.Unchecked)

    def _invert(self):
        for i in range(self.list.count()):
            li = self.list.item(i)
            li.setCheckState(
                Qt.Unchecked
                if li.checkState() == Qt.Checked else Qt.Checked)

    def selected_items(self):
        out = []
        for i in range(self.list.count()):
            li = self.list.item(i)
            if li.checkState() == Qt.Checked:
                out.append(self._items[li.data(Qt.UserRole)])
        return out


# ---------------------------------------------------------------- #
#  Event-type filter dialogs                                        #
# ---------------------------------------------------------------- #

class ClickEventFilterDialog(QDialog):
    """Tick which mouse events to record."""

    ITEMS = [
        ("left",         "Left click",     True),
        ("right",        "Right click",    False),
        ("middle",       "Middle click",   False),
        ("scroll_up",    "Scroll up",      False),
        ("scroll_down",  "Scroll down",    False),
        ("scroll_left",  "Scroll left",    False),
        ("scroll_right", "Scroll right",   False),
        ("back",         "Side button 1 (back)",    False),
        ("forward",      "Side button 2 (forward)", False),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Which mouse events?")
        self.setModal(True)
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        head = QLabel("Tick the events to record.")
        head.setStyleSheet("font-weight:600;color:#F0F0F0;")
        v.addWidget(head)

        self._boxes = {}
        for key, label, default in self.ITEMS:
            cb = QCheckBox(label)
            cb.setChecked(default)
            v.addWidget(cb)
            self._boxes[key] = cb

        row = QHBoxLayout()
        b_all  = QPushButton("All")
        b_none = QPushButton("None")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)
        b_ok = QPushButton("OK")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_cancel)
        row.addWidget(b_ok)
        v.addLayout(row)

    def _set_all(self, on):
        for cb in self._boxes.values():
            cb.setChecked(on)

    def selected(self):
        return {k for k, cb in self._boxes.items() if cb.isChecked()}


class KeyEventFilterDialog(QDialog):
    """Tick which categories of keys to record."""

    ITEMS = [
        ("letters",    "Letters (a-z)",            True),
        ("numbers",    "Numbers (0-9)",            True),
        ("function",   "Function keys (F1-F24)",   True),
        ("modifiers",  "Modifiers (Ctrl/Shift/Alt/Win)", True),
        ("arrows",     "Arrow keys",               True),
        ("whitespace", "Space, Tab, Enter",        True),
        ("editing",    "Backspace, Delete, Insert", True),
        ("navigation", "Home, End, PgUp, PgDn",    True),
        ("symbols",    "Punctuation / symbols",    True),
        ("media",      "Media keys (Play, Vol, ...)", True),
        ("system",     "Esc, PrintScreen, Lock keys", True),
        ("other",      "Anything else",            True),
    ]

    def __init__(self, parent=None, kind="press"):
        super().__init__(parent)
        self.setWindowTitle("Which keys?")
        self.setModal(True)
        self.setMinimumWidth(400)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(6)

        head = QLabel("Tick the key categories to record.")
        head.setStyleSheet("font-weight:600;color:#F0F0F0;")
        v.addWidget(head)

        self._boxes = {}
        for key, label, default in self.ITEMS:
            cb = QCheckBox(label)
            cb.setChecked(default)
            v.addWidget(cb)
            self._boxes[key] = cb

        row = QHBoxLayout()
        b_all  = QPushButton("All")
        b_none = QPushButton("None")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)
        b_ok = QPushButton("OK")
        b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_cancel)
        row.addWidget(b_ok)
        v.addLayout(row)

    def _set_all(self, on):
        for cb in self._boxes.values():
            cb.setChecked(on)

    def selected(self):
        return {k for k, cb in self._boxes.items() if cb.isChecked()}


def _classify_key(name):
    """Return the category for a key name, matching KeyEventFilterDialog."""
    if not name:
        return "other"
    if name in ("ctrl", "shift", "alt", "win", "hyper"):
        return "modifiers"
    if name == "esc":
        return "system"
    if name in ("space", "tab", "enter"):
        return "whitespace"
    if name in ("backspace", "delete", "insert"):
        return "editing"
    if name in ("home", "end", "pageup", "pagedown"):
        return "navigation"
    if name in ("up", "down", "left", "right"):
        return "arrows"
    if name in ("printscreen", "pause", "numlock",
                "scrolllock", "capslock"):
        return "system"
    if name in ("mute", "volumedown", "volumeup",
                "playpause", "nextsong", "prevsong",
                "stop", "eject"):
        return "media"
    if len(name) == 1:
        if name.isalpha():
            return "letters"
        if name.isdigit():
            return "numbers"
        return "symbols"
    if name.startswith("f") and name[1:].isdigit():
        return "function"
    return "other"


# ---------------------------------------------------------------- #
#  install()                                                        #
# ---------------------------------------------------------------- #

def install(Node_cls, NodeSocket_cls):
    for name in dir(_NodeWidgetHost):
        if name.startswith("__"):
            continue
        attr = getattr(_NodeWidgetHost, name)
        if callable(attr):
            setattr(Node_cls, name, attr)

    old_init = Node_cls.__init__
    def _init_wrap(self, *a, **kw):
        old_init(self, *a, **kw)
        if not hasattr(self, "_attached_widgets"):
            self._attached_widgets = []
    Node_cls.__init__ = _init_wrap

    old_layout = Node_cls.layout
    def _layout_wrap(self, *a, **kw):
        old_layout(self, *a, **kw)
        reserved = self._widgets_reserved_height()
        if reserved:
            self.prepareGeometryChange()
            self.height += reserved
            try:
                self._output_rect = self._output_rect.translated(0, reserved)
            except Exception:
                pass
        self.layout_custom()
        self.update_edges()
        self.update()
    Node_cls.layout = _layout_wrap

    def _socket_set_value(self, value):
        self.value = value
        for fn in getattr(self, "_value_listeners", []):
            try:
                fn(value)
            except Exception as ex:
                print("[socket] listener:", ex)
        try:
            self.node.update()
        except Exception:
            pass
    NodeSocket_cls.set_value = _socket_set_value

    # Build the concrete subclasses from the registered factories.
    global LIVE_NODE_CLASSES
    LIVE_NODE_CLASSES.clear()
    for _tag, _factory in list(_NODE_CLASS_REGISTRY.items()):
        try:
            LIVE_NODE_CLASSES[_tag] = _factory(Node_cls)
        except Exception as _fex:
            print("[nodehost] factory %r failed: %s"
                  % (_tag, _fex))
    print("[nodehost] live classes:",
          sorted(LIVE_NODE_CLASSES.keys()))
    print("[nodehost] installed on %s and %s"
          % (Node_cls.__name__, NodeSocket_cls.__name__))


# ---------------------------------------------------------------- #
#  Factories for pyautogui click / press / hotkey                   #
# ---------------------------------------------------------------- #

@register_node_class("click")
def _make_click(Node):
    class ClickNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\U0001F5B1",
                on_click=self._on_capture,
                tooltip="Capture one click into x / y",
                anchor=ANCHOR_HEADER, w=26, h=18)
            self.add_button(
                "\U0001F522",
                on_click=self._on_capture_multi,
                tooltip="Capture multiple clicks",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_capture(self):
            self.capture_click("x", "y")
        def _on_capture_multi(self):
            self._open_multi_capture("click",
                                     x_socket="x", y_socket="y")
    return ClickNode


@register_node_class("hotkey")
def _make_hotkey(Node):
    class HotkeyNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\u2328",
                on_click=self._on_capture,
                tooltip="Capture one hotkey into *args",
                anchor=ANCHOR_HEADER, w=26, h=18)
            self.add_button(
                "\U0001F522",
                on_click=self._on_capture_multi,
                tooltip="Capture multiple hotkeys",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_capture(self):
            self.capture_hotkey("*args", multi=True)
        def _on_capture_multi(self):
            self._open_multi_capture("hotkey", target_socket="*args")
    return HotkeyNode


@register_node_class("press")
def _make_press(Node):
    class PressNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\u2328",
                on_click=self._on_capture,
                tooltip="Capture one key into *args",
                anchor=ANCHOR_HEADER, w=26, h=18)
            self.add_button(
                "\U0001F522",
                on_click=self._on_capture_multi,
                tooltip="Capture multiple keys",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_capture(self):
            self.capture_press("*args")
        def _on_capture_multi(self):
            self._open_multi_capture("press", target_socket="*args")
    return PressNode


# ---------------------------------------------------------------- #
#  File browser buttons                                             #
# ---------------------------------------------------------------- #

@register_node_class("file_open")
def _make_file_open(Node):
    class FileOpenNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\U0001F4C1",
                on_click=self._on_pick,
                tooltip="Browse for a file to open",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_pick(self):
            self._open_file_browser("Path", save=False)
    return FileOpenNode


@register_node_class("file_read")
def _make_file_read(Node):
    class FileReadNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\U0001F4C1",
                on_click=self._on_pick,
                tooltip="Browse for a file to read",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_pick(self):
            self._open_file_browser("Path", save=False)
    return FileReadNode


@register_node_class("file_write")
def _make_file_write(Node):
    class FileWriteNode(Node):
        def after_template_built(self, template):
            self.add_button(
                "\U0001F4BE",
                on_click=self._on_pick,
                tooltip="Choose where to save",
                anchor=ANCHOR_HEADER, w=26, h=18)
        def _on_pick(self):
            self._open_file_browser("Path", save=True)
    return FileWriteNode
