#!/usr/bin/env python3
"""
fix_run_handlers.py — install the missing ask/media dispatch in
_on_run_line and the _handle_ask / _handle_media methods.

Every previous attempt to patch _on_run_line looked for an existing
`if cmd == "ask":` branch.  On this copy of Nodes.py that branch was
never installed — the original file went straight from
`payload = parts[2] ...` to the node lookup, so neither the ask nor
the media protocol had any handler.

This script anchors on the one line that is present in every version
of _on_run_line:

    payload = parts[2] if len(parts) > 2 else ""

It inserts the two protocol branches immediately after, and then
verifies that MainWindow has _handle_ask and _handle_media methods,
inserting them if not.

Idempotent.  Backs up Nodes.py to Nodes.py.bak_runhandlers.
"""

import os
import re
import shutil
import py_compile
import sys


def _find_nodes():
    for p in ("helpers/Nodes/Nodes.py", "Nodes.py"):
        if os.path.isfile(p):
            return p
    return None


# ===================================================================== #
#  Dispatch insertion                                                  #
# ===================================================================== #

DISPATCH_BLOCK = '''\

        # Commands that must run before any node lookup.
        if cmd == "ask":
            self._handle_ask(nid, payload)
            return
        if cmd == "media":
            self._handle_media(nid, payload)
            return
'''


def _insert_dispatch(src):
    """
    Insert the ask / media branches right after the payload extraction
    inside _on_run_line.  Returns (src, n_changes).
    """
    if 'if cmd == "ask":' in src and 'if cmd == "media":' in src:
        return src, 0

    lines = src.split("\n")

    # Find _on_run_line
    s = None
    for i, ln in enumerate(lines):
        if re.match(r'^\s*def _on_run_line\s*\(', ln):
            s = i
            break
    if s is None:
        print("  [!!] _on_run_line not found")
        return src, 0

    # Anchor on the payload line inside it
    anchor = None
    for j in range(s, min(s + 40, len(lines))):
        if 'payload = parts[2]' in lines[j]:
            anchor = j
            break
    if anchor is None:
        print("  [!!] payload line not found inside _on_run_line")
        return src, 0

    indent = re.match(r'^(\s*)', lines[anchor]).group(1)
    insert = [
        "",
        indent + "# Commands that must run before any node lookup.",
        indent + 'if cmd == "ask":',
        indent + "    self._handle_ask(nid, payload)",
        indent + "    return",
        indent + 'if cmd == "media":',
        indent + "    self._handle_media(nid, payload)",
        indent + "    return",
    ]
    new_lines = lines[:anchor + 1] + insert + lines[anchor + 1:]
    return "\n".join(new_lines), 1


# ===================================================================== #
#  Handler method bodies                                               #
# ===================================================================== #

HANDLE_ASK = '''\
    def _handle_ask(self, nid, payload):
        try:
            prompt = json.loads(payload)
        except Exception:
            prompt = str(payload)
        from PyQt5.QtWidgets import QInputDialog
        self._show_run_dialog()
        text, ok = QInputDialog.getText(
            self, "Input required",
            str(prompt) if prompt else "Enter value:")
        reply = text if ok else ""
        proc = getattr(getattr(self, "_run_thread", None), "_proc", None)
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.write(reply + "\\n")
                proc.stdin.flush()
            except Exception as ex:
                print("[ask] write failed:", ex)
        try:
            self._run_log.append("> %s%s" % (prompt, reply))
        except Exception:
            pass

'''

HANDLE_MEDIA = '''\
    def _handle_media(self, nid, payload):
        try:
            info = json.loads(payload)
            kind = info.get("kind", "")
            path = info.get("path", "")
        except Exception:
            return
        if not path or not os.path.isfile(path):
            return
        if kind == "image":
            self._show_image_dialog(nid, path)
        elif kind in ("audio", "video"):
            self._show_media_player(nid, path, kind)

    def _show_image_dialog(self, nid, path):
        from PyQt5.QtGui import QPixmap
        dlg = QDialog(self)
        dlg.setWindowTitle("Image \\u2014 %s" % nid)
        dlg.setStyleSheet("QDialog{background:#202020;}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(8, 8, 8, 8)
        pix = QPixmap(path)
        lbl = QLabel()
        if pix.width() > 900 or pix.height() > 640:
            pix = pix.scaled(900, 640, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
        lbl.setPixmap(pix)
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl, 1)
        info = QLabel(os.path.basename(path))
        info.setStyleSheet("color:#8A8A8A;font-size:11px;")
        v.addWidget(info)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        row.addWidget(btn)
        v.addLayout(row)
        dlg.resize(min(pix.width() + 32, 960),
                   min(pix.height() + 96, 760))
        if not hasattr(self, "_media_dialogs"):
            self._media_dialogs = []
        self._media_dialogs.append(dlg)
        dlg.show()
        dlg.raise_()

    def _show_media_player(self, nid, path, kind):
        try:
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
            from PyQt5.QtMultimediaWidgets import QVideoWidget
            from PyQt5.QtCore import QUrl
        except Exception as ex:
            self.report("QtMultimedia unavailable: %s" % ex,
                        "warning", 4000)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("%s \\u2014 %s"
                          % (kind.capitalize(), nid))
        dlg.setStyleSheet("QDialog{background:#202020;}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(8, 8, 8, 8)
        if kind == "video":
            widget = QVideoWidget()
            v.addWidget(widget, 1)
            player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
            player.setVideoOutput(widget)
        else:
            lbl = QLabel(os.path.basename(path))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#DDD;font-size:14px;")
            v.addWidget(lbl, 1)
            player = QMediaPlayer()
        player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        row = QHBoxLayout()
        btn_play  = QPushButton("Play")
        btn_pause = QPushButton("Pause")
        btn_stop  = QPushButton("Stop")
        row.addWidget(btn_play)
        row.addWidget(btn_pause)
        row.addWidget(btn_stop)
        row.addStretch(1)
        v.addLayout(row)
        btn_play.clicked.connect(player.play)
        btn_pause.clicked.connect(player.pause)
        btn_stop.clicked.connect(player.stop)
        player.play()
        if not hasattr(self, "_media_dialogs"):
            self._media_dialogs = []
        self._media_dialogs.append((dlg, player))
        dlg.resize(800, 600 if kind == "video" else 200)
        dlg.show()
        dlg.raise_()

'''


def _method_exists(src, name):
    return re.search(r'^\s*def ' + re.escape(name) + r'\s*\(', src,
                     re.MULTILINE) is not None


def _insert_methods(src):
    """
    Insert _handle_ask and _handle_media (and their helpers) if
    missing.  Insert them right before _on_run_finished if that method
    exists, otherwise right before _on_run_line.
    """
    added = 0
    if not _method_exists(src, "_handle_ask"):
        src = _insert_before(src, "_on_run_finished", HANDLE_ASK)
        if src is None:
            src = _insert_before(src, "_on_run_line", HANDLE_ASK)
        added += 1
    if not _method_exists(src, "_handle_media"):
        src = _insert_before(src, "_on_run_finished", HANDLE_MEDIA)
        if src is None:
            src = _insert_before(src, "_on_run_line", HANDLE_MEDIA)
        added += 1
    return src, added


def _insert_before(src, method_name, text):
    """
    Insert `text` right before `def <method_name>(` at any indentation.
    Returns the new source or None if the anchor isn't found.
    """
    lines = src.split("\n")
    s = None
    for i, ln in enumerate(lines):
        if re.match(r'^\s*def ' + re.escape(method_name) + r'\s*\(', ln):
            s = i
            break
    if s is None:
        return None
    add = text.rstrip("\n").split("\n")
    new_lines = lines[:s] + add + [""] + lines[s:]
    return "\n".join(new_lines)


# ===================================================================== #
#  Main                                                                #
# ===================================================================== #

def main():
    path = _find_nodes()
    if not path:
        print("Could not find helpers/Nodes/Nodes.py or Nodes.py")
        sys.exit(1)

    print("Target:", path)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    applied = 0

    # 1. Dispatch branches
    if 'if cmd == "ask":' in src and 'if cmd == "media":' in src:
        print("  [ok] dispatch branches already present")
    else:
        src, n = _insert_dispatch(src)
        if n:
            applied += n
            print("  [+] ask + media dispatch inserted into _on_run_line")

    # 2. Handler methods
    src, n = _insert_methods(src)
    if n:
        applied += n
        print("  [+] %d handler method(s) inserted" % n)
    else:
        print("  [ok] handler methods already present")

    if applied == 0:
        print()
        print("Nothing to do — everything is already in place.")
        return

    backup = path + ".bak_runhandlers"
    shutil.copy(path, backup)
    print()
    print("Backup ->", backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    try:
        py_compile.compile(path, doraise=True)
        print("Syntax OK.  %d change(s) applied." % applied)
    except py_compile.PyCompileError as e:
        shutil.copy(backup, path)
        print("! syntax error — restored from backup")
        print(e)
        sys.exit(1)

    print()
    print("Verify with:")
    print("    grep -n '_handle_ask\\|_handle_media\\|cmd == \"ask\"' "
          "helpers/Nodes/Nodes.py")
    print()
    print("Then run:")
    print("    python main.py")
    print()
    print("Now `input` nodes pop a QInputDialog and media nodes pop a")
    print("viewer during the run.")


if __name__ == "__main__":
    main()