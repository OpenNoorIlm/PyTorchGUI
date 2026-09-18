"""
NodeClasses.py — full PyQt5 control over every node.

Installs a "widget host" onto Node and NodeSocket.  From then on,
every node is a real Qt container: any QWidget can be attached to it
at a named anchor (header / row / section / socket / footer / free),
and can be bound bidirectionally to any socket.

Then register per-template behaviour with a decorator or by calling
the attach/bind methods directly.

Usage
-----

    from helpers.Nodes.NodeClasses import (
        ANCHOR_ROW, ANCHOR_HEADER, ANCHOR_SECTION, ANCHOR_SOCKET,
        ANCHOR_FOOTER, ANCHOR_FREE,
        register_node_class,
    )

    @register_node_class("click")
    def _make_click(Node):
        class ClickNode(Node):
            def after_template_built(self, template):
                self.add_button("🖱 capture", on_click=self._capture)
            def _capture(self):
                self.capture_click("x", "y")
        return ClickNode
"""

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF
from PyQt5.QtGui import QCursor, QColor, QFont
from PyQt5.QtWidgets import (
    QGraphicsProxyWidget, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QLabel, QSlider, QSpinBox, QDoubleSpinBox, QPlainTextEdit,
    QProgressBar, QWidget, QDialog, QVBoxLayout, QLabel as _Q,
    QMessageBox, QApplication, QToolButton, QTextEdit,
)


# ============================================================== #
#  Anchors                                                       #
# ============================================================== #

ANCHOR_HEADER  = "header"    # top-right of the title bar
ANCHOR_ROW     = "row"       # full-width, stacked top-to-bottom
ANCHOR_SECTION = "section"   # inside a named section, below rows
ANCHOR_SOCKET  = "socket"    # beside a socket circle
ANCHOR_FOOTER  = "footer"    # just above the shell-output strip
ANCHOR_FREE    = "free"      # absolute (x, y), moves with node


# ============================================================== #
#  Registry of Node subclasses                                   #
# ============================================================== #

_NODE_CLASS_REGISTRY = {}


def register_node_class(name):
    """Decorate a factory that takes Node and returns a subclass."""
    def _wrap(factory):
        _NODE_CLASS_REGISTRY[name] = factory
        return factory
    return _wrap


def get_node_class(name):
    return _NODE_CLASS_REGISTRY.get(name)


# ============================================================== #
#  Widget factory helpers                                        #
# ============================================================== #

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


def make_button(text, on_click=None, tooltip=None, style=None, h=22):
    b = QPushButton(text)
    b.setStyleSheet(style or _BTN_STYLE)
    b.setMinimumHeight(h)
    if tooltip:
        b.setToolTip(tooltip)
    if on_click:
        b.clicked.connect(lambda _c=False: on_click())
    return b


def make_line_edit(text="", placeholder=None, style=None, h=22):
    le = QLineEdit(str(text))
    le.setStyleSheet(style or _EDIT_STYLE)
    le.setMinimumHeight(h)
    if placeholder:
        le.setPlaceholderText(placeholder)
    return le


def make_checkbox(label, checked=False, h=20):
    cb = QCheckBox(str(label))
    cb.setChecked(bool(checked))
    cb.setMinimumHeight(h)
    return cb


def make_combo(items, current=0, h=22):
    cb = QComboBox()
    cb.addItems([str(x) for x in items])
    if 0 <= current < len(items):
        cb.setCurrentIndex(current)
    cb.setMinimumHeight(h)
    return cb


def make_label(text, h=18, style="color:#DDD;font-size:10px;"):
    lb = QLabel(str(text))
    lb.setStyleSheet(style)
    lb.setMinimumHeight(h)
    return lb


def make_slider(minimum=0, maximum=100, value=0, h=22):
    s = QSlider(Qt.Horizontal)
    s.setRange(int(minimum), int(maximum))
    s.setValue(int(value))
    s.setMinimumHeight(h)
    return s


def make_spin(value=0, minimum=-10**9, maximum=10**9, h=22):
    sb = QSpinBox()
    sb.setRange(int(minimum), int(maximum))
    sb.setValue(int(value))
    sb.setMinimumHeight(h)
    return sb


def make_dspin(value=0.0, minimum=-1e12, maximum=1e12, h=22):
    sb = QDoubleSpinBox()
    sb.setRange(float(minimum), float(maximum))
    sb.setValue(float(value))
    sb.setMinimumHeight(h)
    return sb


def make_progress(value=0, h=14):
    pb = QProgressBar()
    pb.setRange(0, 100)
    pb.setValue(int(value))
    pb.setTextVisible(False)
    pb.setMinimumHeight(h)
    return pb


def make_text_edit(text="", h=60):
    te = QPlainTextEdit()
    te.setPlainText(str(text))
    te.setMinimumHeight(h)
    return te


# ============================================================== #
#  Capture overlays (used by capture_click / capture_hotkey)    #
# ============================================================== #

class CaptureOverlay(QWidget):
    def __init__(self, passthrough=True, on_click=None):
        super().__init__(None,
                         Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self._passthrough = bool(passthrough)
        self._on_click = on_click
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.15)
        self.setStyleSheet("background:#101010;")
        try:
            geo = QApplication.primaryScreen().virtualGeometry()
        except Exception:
            geo = QApplication.primaryScreen().geometry()
        self.setGeometry(geo)
        self._prev = Qt.NoButton
        self._poll = None
        if self._passthrough:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._poll = QTimer(self)
            self._poll.setInterval(10)
            self._poll.timeout.connect(self._poll_mouse)
        else:
            self.setCursor(Qt.CrossCursor)

    def start(self):
        self.show(); self.raise_(); self.activateWindow()
        if self._poll:
            self._prev = QApplication.mouseButtons()
            self._poll.start()

    def _poll_mouse(self):
        st = QApplication.mouseButtons()
        fired = (self._prev == Qt.NoButton and st != Qt.NoButton)
        self._prev = st
        if fired:
            p = QCursor.pos()
            self._finish(p.x(), p.y())

    def mousePressEvent(self, event):
        if self._passthrough:
            event.ignore(); return
        p = event.globalPos()
        self._finish(p.x(), p.y())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def _finish(self, x, y):
        if self._poll:
            self._poll.stop()
        self.close()
        if self._on_click:
            try:
                self._on_click(int(x), int(y))
            except Exception as ex:
                print("[capture] on_click:", ex)


_QT_KEY_NAMES = {
    Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
    Qt.Key_Escape: "esc", Qt.Key_Tab: "tab",
    Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert", Qt.Key_Home: "home",
    Qt.Key_End: "end", Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
    Qt.Key_Right: "right", Qt.Key_Space: "space",
    Qt.Key_CapsLock: "capslock", Qt.Key_NumLock: "numlock",
    Qt.Key_ScrollLock: "scrolllock", Qt.Key_Pause: "pause",
    Qt.Key_Print: "printscreen",
}
_PUNCT = {
    Qt.Key_Minus: "-", Qt.Key_Equal: "=",
    Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
    Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'",
    Qt.Key_Comma: ",", Qt.Key_Period: ".", Qt.Key_Slash: "/",
    Qt.Key_Backslash: "\\", Qt.Key_QuoteLeft: "`",
}


def _qt_key_name(k):
    if k in _QT_KEY_NAMES:
        return _QT_KEY_NAMES[k]
    if Qt.Key_A <= k <= Qt.Key_Z:
        return chr(k).lower()
    if Qt.Key_0 <= k <= Qt.Key_9:
        return chr(k)
    if Qt.Key_F1 <= k <= Qt.Key_F24:
        return "f%d" % (k - Qt.Key_F1 + 1)
    return _PUNCT.get(k)


class KeyCaptureDialog(QDialog):
    def __init__(self, parent=None, multi=True):
        super().__init__(parent)
        self.setWindowTitle("Capture hotkey" if multi else "Capture key")
        self.setModal(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(340, 130)
        self.result_keys = None
        self._multi = multi
        v = QVBoxLayout(self)
        msg = QLabel("Press the combination now.\nEscape cancels."
                     if multi else "Press a single key.\nEscape cancels.")
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("color:#DDD;font-size:12px;")
        v.addWidget(msg)
        self.preview = QLabel("—")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "color:#E08C4A;font-size:18px;font-weight:bold;padding:8px;")
        v.addWidget(self.preview)

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key_Escape:
            self.reject(); return
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt,
                 Qt.Key_Meta, Qt.Key_AltGr):
            return
        n = _qt_key_name(k)
        if n is None:
            return
        keys = []
        if self._multi:
            m = event.modifiers()
            if m & Qt.ControlModifier: keys.append("ctrl")
            if m & Qt.ShiftModifier:   keys.append("shift")
            if m & Qt.AltModifier:     keys.append("alt")
            if m & Qt.MetaModifier:    keys.append("win")
        keys.append(n)
        self.result_keys = keys
        self.preview.setText(" + ".join(keys))
        QTimer.singleShot(120, self.accept)


# ============================================================== #
#  The host mixin — installed onto Node                          #
# ============================================================== #

class _NodeWidgetHost:

    # ------------------------------------------------------ #
    #  Core attachment                                       #
    # ------------------------------------------------------ #

    def attach(self, widget, anchor=ANCHOR_ROW, h=None, w=None,
               key=None, side="right", x=0, y=0):
        """Attach any QWidget to this node."""
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

    def attached_widgets(self):
        return list(getattr(self, "_attached_widgets", []))

    # ------------------------------------------------------ #
    #  Convenience wrappers                                  #
    # ------------------------------------------------------ #

    def add_button(self, text, on_click=None, tooltip=None, style=None,
                   anchor=ANCHOR_ROW, h=22, w=None, key=None, side="right",
                   x=0, y=0):
        b = make_button(text, on_click, tooltip, style, h=h)
        return self.attach(b, anchor=anchor, h=h, w=w, key=key,
                           side=side, x=x, y=y)

    def add_line_edit(self, text="", placeholder=None, socket_name=None,
                      anchor=ANCHOR_ROW, h=22, w=None, key=None,
                      side="right", x=0, y=0, transform=None):
        le = make_line_edit(text, placeholder, h=h)
        self.attach(le, anchor=anchor, h=h, w=w, key=key,
                    side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                le, "textChanged", socket_name,
                transform=transform or (lambda t: repr(str(t))))
            self.bind_socket_to_widget(
                socket_name, le, "setText",
                transform=lambda v: "" if v is None else str(v))
        return le

    def add_checkbox(self, label, checked=False, socket_name=None,
                     anchor=ANCHOR_ROW, h=20, key=None, side="right",
                     x=0, y=0):
        cb = make_checkbox(label, checked, h=h)
        self.attach(cb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                cb, "toggled", socket_name,
                transform=lambda b: repr(bool(b)))
            self.bind_socket_to_widget(
                socket_name, cb, "setChecked",
                transform=lambda v: bool(v) if not isinstance(v, str)
                          else v.strip().lower() in ("true", "1", "yes"))
        return cb

    def add_combo(self, items, current=0, socket_name=None,
                  anchor=ANCHOR_ROW, h=22, key=None, side="right",
                  x=0, y=0):
        cb = make_combo(items, current, h=h)
        self.attach(cb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                cb, "currentTextChanged", socket_name,
                transform=lambda t: repr(str(t)))
        return cb

    def add_label(self, text, anchor=ANCHOR_ROW, h=18, key=None,
                  side="right", x=0, y=0, style=None):
        lb = make_label(text, h=h)
        if style:
            lb.setStyleSheet(style)
        return self.attach(lb, anchor=anchor, h=h, key=key,
                           side=side, x=x, y=y)

    def add_slider(self, minimum=0, maximum=100, value=0,
                   socket_name=None, anchor=ANCHOR_ROW, h=22,
                   key=None, side="right", x=0, y=0):
        s = make_slider(minimum, maximum, value, h=h)
        self.attach(s, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                s, "valueChanged", socket_name,
                transform=lambda v: repr(int(v)))
            self.bind_socket_to_widget(
                socket_name, s, "setValue",
                transform=lambda v: int(v) if not isinstance(v, str)
                          else int(float(v)))
        return s

    def add_spin(self, value=0, minimum=-10**9, maximum=10**9,
                 socket_name=None, anchor=ANCHOR_ROW, h=22, key=None,
                 side="right", x=0, y=0):
        sb = make_spin(value, minimum, maximum, h=h)
        self.attach(sb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                sb, "valueChanged", socket_name,
                transform=lambda v: repr(int(v)))
            self.bind_socket_to_widget(
                socket_name, sb, "setValue",
                transform=lambda v: int(v) if not isinstance(v, str)
                          else int(float(v)))
        return sb

    def add_dspin(self, value=0.0, minimum=-1e12, maximum=1e12,
                  socket_name=None, anchor=ANCHOR_ROW, h=22, key=None,
                  side="right", x=0, y=0):
        sb = make_dspin(value, minimum, maximum, h=h)
        self.attach(sb, anchor=anchor, h=h, key=key, side=side, x=x, y=y)
        if socket_name:
            self.bind_widget_to_socket(
                sb, "valueChanged", socket_name,
                transform=lambda v: repr(float(v)))
            self.bind_socket_to_widget(
                socket_name, sb, "setValue",
                transform=lambda v: float(v) if not isinstance(v, str)
                          else float(v))
        return sb

    def add_progress(self, anchor=ANCHOR_ROW, h=14, key=None):
        pb = make_progress(h=h)
        return self.attach(pb, anchor=anchor, h=h, key=key)

    def add_text_edit(self, text="", anchor=ANCHOR_ROW, h=60, key=None):
        te = make_text_edit(text, h=h)
        return self.attach(te, anchor=anchor, h=h, key=key)

    # ------------------------------------------------------ #
    #  Signal <-> socket binding                             #
    # ------------------------------------------------------ #

    def bind_widget_to_socket(self, widget, signal_name, socket_name,
                              is_input=True, transform=None):
        """When the widget emits `signal_name`, write into the socket."""
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
            sock.set_value(v)
            self.update()

        try:
            getattr(widget, signal_name).connect(_on_signal)
        except Exception as ex:
            print("[bind] %s.%s:" % (type(widget).__name__, signal_name), ex)
            return False
        return True

    def bind_socket_to_widget(self, socket_name, widget, setter_name,
                              is_input=True, transform=None):
        """When the socket's literal changes, update the widget."""
        sock = self.socket(socket_name, is_input=is_input)
        if sock is None:
            return False

        def _apply(value):
            try:
                v = transform(value) if transform is not None else value
                getattr(widget, setter_name)(v)
            except Exception:
                pass

        if not hasattr(sock, "_value_listeners"):
            sock._value_listeners = []
        sock._value_listeners.append(_apply)
        return True

    # ------------------------------------------------------ #
    #  Capture helpers                                       #
    # ------------------------------------------------------ #

    def capture_click(self, x_socket="x", y_socket="y"):
        """Prompt for passthrough, then record the next click into x/y."""
        try:
            box = QMessageBox(self._view_window())
            box.setWindowTitle("Capture click")
            box.setText("The next click will be recorded.")
            box.setInformativeText(
                "Should the operating system also receive that click?\n\n"
                "Yes — click reaches the window under the cursor, "
                "AND is recorded here.\n"
                "No  — click is recorded here and swallowed.")
            yes = box.addButton("Yes (passthrough)", QMessageBox.YesRole)
            no  = box.addButton("No (capture only)", QMessageBox.NoRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec_()
            btn = box.clickedButton()
            if btn is None or btn is box.buttons()[-1]:
                return
            passthrough = (btn is yes)
        except Exception as ex:
            print("[capture_click] ask:", ex)
            passthrough = True

        def _done(x, y):
            xs = self.socket(x_socket, is_input=True)
            ys = self.socket(y_socket, is_input=True)
            if xs: xs.set_value(str(int(x)))
            if ys: ys.set_value(str(int(y)))
            self.update()

        overlay = CaptureOverlay(passthrough=passthrough, on_click=_done)
        overlay.start()
        self._capture_overlay = overlay

    def capture_hotkey(self, target_socket="*args", multi=True):
        dlg = KeyCaptureDialog(self._view_window(), multi=multi)
        if dlg.exec_() != dlg.Accepted or not dlg.result_keys:
            return
        sock = self.socket(target_socket, is_input=True)
        if sock is None:
            print("[capture_hotkey] no socket %r" % target_socket); return
        sock.set_value(repr(list(dlg.result_keys)))
        self.update()

    def capture_press(self, target_socket="*args"):
        self.capture_hotkey(target_socket, multi=False)

    # ------------------------------------------------------ #
    #  Layout                                                #
    # ------------------------------------------------------ #

    def layout_custom(self):
        recs = getattr(self, "_attached_widgets", None)
        if not recs:
            return
        row_y = getattr(self, "_body_top", 36)
        for rec in recs:
            self._place_widget(rec, row_y)
            if rec["anchor"] == ANCHOR_ROW:
                row_y += rec["h"] + 4

    def _place_widget(self, rec, row_y):
        proxy = rec["proxy"]
        nw = self.width

        if rec["anchor"] == ANCHOR_HEADER:
            w = rec["w"] or 84
            x, y = nw - w - 6, 4
        elif rec["anchor"] == ANCHOR_ROW:
            w = rec["w"] or (nw - 16)
            x, y = (nw - w) / 2.0, row_y
        elif rec["anchor"] == ANCHOR_SECTION:
            sec = self._section_by_name(rec["key"])
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
            out = self._output_rect
            y = out.top() - rec["h"] - 4
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

    def _section_by_name(self, name):
        for sec in self.sections:
            if sec["name"] == name:
                return sec
        return None

    def _widgets_reserved_height(self):
        total = 0
        for rec in getattr(self, "_attached_widgets", []):
            if rec["anchor"] in (ANCHOR_ROW, ANCHOR_SECTION, ANCHOR_FOOTER):
                total += rec["h"] + 4
        return (total + 4) if total else 0

    def after_template_built(self, template):
        """Overridable hook."""
        pass

    def _view_window(self):
        try:
            v = self.scene().views()
            if v:
                return v[0].window()
        except Exception:
            pass
        return None


# ============================================================== #
#  install() — patch Node and NodeSocket                         #
# ============================================================== #

def install(Node_cls, NodeSocket_cls):
    """
    Called by Nodes.py after both classes are defined.
    Copies _NodeWidgetHost methods onto Node, and adds set_value()
    to NodeSocket so widget<->socket bindings can dispatch.
    """

    # 1. Methods onto Node
    for name in dir(_NodeWidgetHost):
        if name.startswith("__"):
            continue
        attr = getattr(_NodeWidgetHost, name)
        if callable(attr):
            setattr(Node_cls, name, attr)

    # 2. Ensure _attached_widgets exists on every Node instance
    old_init = Node_cls.__init__
    def _init_wrap(self, *a, **kw):
        old_init(self, *a, **kw)
        if not hasattr(self, "_attached_widgets"):
            self._attached_widgets = []
        self._body_top = 36
    Node_cls.__init__ = _init_wrap

    # 3. Wrap layout so widget space is reserved below the sections
    old_layout = Node_cls.layout
    def _layout_wrap(self, *a, **kw):
        old_layout(self, *a, **kw)          # core layout, resets height
        reserved = self._widgets_reserved_height()
        if reserved:
            self.prepareGeometryChange()
            self.height += reserved
            # shift the shell strip and its rect down by `reserved`
            self._output_rect = self._output_rect.translated(0, reserved)
        # our own placement
        self.layout_custom()
        self.update_edges()
        self.update()
    Node_cls.layout = _layout_wrap

    # 4. NodeSocket.set_value dispatches to listeners
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

    # 5. Serialization hook: emit current widget values with to_dict
    old_to_dict = getattr(Node_cls, "to_dict", None)
    if old_to_dict is not None:
        def _to_dict_wrap(self):
            d = old_to_dict(self)
            d["widget_state"] = _collect_widget_state(self)
            return d
        Node_cls.to_dict = _to_dict_wrap

    print("[nodehost] installed on %s and %s"
          % (Node_cls.__name__, NodeSocket_cls.__name__))


def _collect_widget_state(self):
    out = []
    for rec in getattr(self, "_attached_widgets", []):
        w = rec["widget"]
        entry = {"anchor": rec["anchor"], "key": rec["key"],
                 "side": rec["side"], "x": rec["x"], "y": rec["y"],
                 "h": rec["h"], "w": rec["w"]}
        try:
            if isinstance(w, QLineEdit):        entry["value"] = w.text()
            elif isinstance(w, QCheckBox):      entry["value"] = w.isChecked()
            elif isinstance(w, QComboBox):      entry["value"] = w.currentText()
            elif isinstance(w, QSlider):        entry["value"] = w.value()
            elif isinstance(w, QSpinBox):       entry["value"] = w.value()
            elif isinstance(w, QDoubleSpinBox): entry["value"] = w.value()
            elif isinstance(w, QPushButton):    entry["value"] = w.text()
            elif isinstance(w, QLabel):         entry["value"] = w.text()
            elif isinstance(w, QPlainTextEdit): entry["value"] = w.toPlainText()
        except Exception:
            pass
        out.append(entry)
    return out


# ============================================================== #
#  Example per-template classes (pyautogui)                      #
# ============================================================== #

@register_node_class("click")
def _make_click(Node):
    class ClickNode(Node):
        def after_template_built(self, template):
            self.add_button("🖱  capture click",
                            on_click=self._on_capture,
                            tooltip="Record the next click into x/y")
        def _on_capture(self):
            self.capture_click("x", "y")
    return ClickNode


@register_node_class("hotkey")
def _make_hotkey(Node):
    class HotkeyNode(Node):
        def after_template_built(self, template):
            self.add_button("⌨  capture hotkey",
                            on_click=self._on_capture,
                            tooltip="Press a combination; keys go into *args")
        def _on_capture(self):
            self.capture_hotkey("*args", multi=True)
    return HotkeyNode


@register_node_class("press")
def _make_press(Node):
    class PressNode(Node):
        def after_template_built(self, template):
            self.add_button("⌨  capture key",
                            on_click=self._on_capture,
                            tooltip="Press a single key")
        def _on_capture(self):
            self.capture_press("*args")
    return PressNode