#!/usr/bin/env python3
"""
edit_filter_ui.py — add a search bar and Expand/Collapse All to the
library filter dialog.

The dialog now has:

    ┌─ Filter node library ────────────────────┐
    │ Show these categories                    │
    │ Uncheck a category to hide every node    │
    │ inside it.                               │
    │ ┌──────────────────────────────────────┐ │
    │ │ 🔍  Search…                          │ │
    │ └──────────────────────────────────────┘ │
    │ [Expand All] [Collapse All]              │
    │ ┌──────────────────────────────────────┐ │
    │ │ ☑ Torch                              │ │
    │ │     ☑ nn                             │ │
    │ │         ☑ modules                    │ │
    │ │ ...                                  │ │
    │ └──────────────────────────────────────┘ │
    │ [Select All] [Select None]  Cancel Apply │
    └──────────────────────────────────────────┘

Search behaviour:
  * Every token must match somewhere in the full path of an item or
    in one of its descendants; matching items stay visible and their
    ancestors are force-visible so the user can see context.
  * Cleared search restores whatever was hidden by the filter.

The tree is replaced wholesale; the new class is idempotent and
py_compile-checked.

Backs up Nodes.py to Nodes.py.bak_filterui.
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


NEW_DIALOG = '''\
class _LibraryFilterDialog(QDialog):
    """Checkbox tree of categories with a search bar and bulk expand."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter node library")
        self.setStyleSheet("QDialog { background:#252525; color:#DDD; }")
        self.resize(440, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        head = QLabel("Show these categories")
        head.setStyleSheet(
            "font-weight:700; color:#F0F0F0; font-size:13px;")
        v.addWidget(head)

        sub = QLabel("Uncheck a category to hide every node inside it.")
        sub.setStyleSheet("color:#8A8A8A; font-size:11px;")
        v.addWidget(sub)

        # --- search row --- #
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search categories\\u2026")
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            "QLineEdit{background:#1E1E1E;color:#DDD;"
            "border:1px solid #333;border-radius:3px;"
            "padding:5px 8px;}"
            "QLineEdit:focus{border:1px solid #E08C4A;}")
        self.search.textChanged.connect(self._on_search)
        v.addWidget(self.search)

        # --- expand / collapse --- #
        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(6)
        btn_expand   = QPushButton("Expand All")
        btn_collapse = QPushButton("Collapse All")
        for b in (btn_expand, btn_collapse):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:#333;color:#DDD;"
                "border:1px solid #4A4A4A;border-radius:3px;"
                "padding:4px 10px;}"
                "QPushButton:hover{background:#3F3F3F;"
                "border:1px solid #E08C4A;}")
        bulk_row.addWidget(btn_expand)
        bulk_row.addWidget(btn_collapse)
        bulk_row.addStretch(1)
        v.addLayout(bulk_row)

        # --- tree --- #
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setStyleSheet(
            "QTreeWidget{background:#1E1E1E; color:#DDD;"
            " border:1px solid #333; outline:0; padding:4px;}"
            "QTreeWidget::item{padding:3px 2px;}"
            "QTreeWidget::item:hover{background:#2E2E2E;}"
            "QTreeWidget::indicator{width:14px;height:14px;}")
        self.tree.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.tree, 1)

        # --- bottom row --- #
        row = QHBoxLayout()
        btn_all  = QPushButton("Select All")
        btn_none = QPushButton("Select None")
        row.addWidget(btn_all)
        row.addWidget(btn_none)
        row.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_apply  = QPushButton("Apply")
        row.addWidget(btn_cancel)
        row.addWidget(btn_apply)
        v.addLayout(row)

        btn_expand.clicked.connect(self.tree.expandAll)
        btn_collapse.clicked.connect(self.tree.collapseAll)
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_cancel.clicked.connect(self.reject)
        btn_apply.clicked.connect(self._apply)

        self._items = {}
        self._build_tree()

    # ---------------------------------------------------------------- #
    #  Tree construction                                               #
    # ---------------------------------------------------------------- #

    def _build_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        for path in _iter_category_paths():
            parts = path.split("/")
            parent = self.tree.invisibleRootItem()
            walked = ""
            for p in parts:
                walked = (walked + "/" + p) if walked else p
                if walked in self._items:
                    parent = self._items[walked]
                    continue
                it = QTreeWidgetItem([p])
                it.setFlags(Qt.ItemIsUserCheckable
                            | Qt.ItemIsEnabled
                            | Qt.ItemIsSelectable)
                checked = walked not in _LIBRARY_FILTER["disabled"]
                it.setCheckState(
                    0, Qt.Checked if checked else Qt.Unchecked)
                it.setData(0, Qt.UserRole, walked)
                parent.addChild(it)
                self._items[walked] = it
                parent = it
        for it in list(self._items.values()):
            if it.childCount():
                self._refresh_tristate(it)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _refresh_tristate(self, item):
        children = [item.child(i) for i in range(item.childCount())]
        if not children:
            return
        states = [c.checkState(0) for c in children]
        if all(s == Qt.Checked for s in states):
            item.setCheckState(0, Qt.Checked)
        elif all(s == Qt.Unchecked for s in states):
            item.setCheckState(0, Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.PartiallyChecked)

    # ---------------------------------------------------------------- #
    #  Checkbox handling                                               #
    # ---------------------------------------------------------------- #

    def _on_item_changed(self, item, col):
        if col != 0:
            return
        self.tree.blockSignals(True)
        state = item.checkState(0)
        if state != Qt.PartiallyChecked:
            self._set_subtree(item, state)
        parent = item.parent()
        while parent is not None:
            self._refresh_tristate(parent)
            parent = parent.parent()
        self.tree.blockSignals(False)

    def _set_subtree(self, item, state):
        item.setCheckState(0, state)
        for i in range(item.childCount()):
            self._set_subtree(item.child(i), state)

    def _set_all(self, on):
        self.tree.blockSignals(True)
        for it in list(self._items.values()):
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self.tree.blockSignals(False)

    # ---------------------------------------------------------------- #
    #  Search                                                          #
    # ---------------------------------------------------------------- #

    def _on_search(self, text):
        tokens = [t for t in text.strip().lower().split() if t]
        for path, it in self._items.items():
            it.setHidden(False)
        if not tokens:
            self.tree.expandAll()
            return

        # mark each node: True if its own path or any descendant matches
        def matches(path):
            low = path.lower()
            return all(t in low for t in tokens)

        def mark(item):
            """Return True if item or any descendant matches."""
            path = item.data(0, Qt.UserRole) or ""
            hit = matches(path)
            any_child = False
            for i in range(item.childCount()):
                c = item.child(i)
                if mark(c):
                    any_child = True
            if not hit and not any_child:
                item.setHidden(True)
                return False
            item.setHidden(False)
            if any_child:
                item.setExpanded(True)
            return True

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            mark(root.child(i))

    # ---------------------------------------------------------------- #
    #  Apply                                                           #
    # ---------------------------------------------------------------- #

    def _apply(self):
        disabled = set()
        for path, it in self._items.items():
            if it.checkState(0) == Qt.Unchecked:
                disabled.add(path)
        _LIBRARY_FILTER["disabled"] = disabled
        try:
            _lib_filter_save()
        except Exception as _e:
            print("[filter] save skipped:", _e)
        win = self.window()
        try:
            win.library.refresh()
        except Exception:
            pass
        try:
            win._persist_settings()
        except Exception:
            pass
        self.accept()
'''


_DIALOG_DEF_RE = re.compile(r'^class\s+_LibraryFilterDialog\s*\(')


def _find_class_range(lines):
    start = None
    for i, ln in enumerate(lines):
        if _DIALOG_DEF_RE.match(ln):
            start = i
            break
    if start is None:
        return None, None

    # Walk to the next top-level def/class
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if not ln.startswith(" ") and not ln.startswith("\t"):
            end = j
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def main():
    path = _find_nodes()
    if not path:
        print("Could not find helpers/Nodes/Nodes.py or Nodes.py")
        sys.exit(1)

    print("Target:", path)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if "self.search.setPlaceholderText(\"Search categories" in src:
        print("  [ok] filter dialog already has the search bar")
        return

    lines = src.split("\n")
    s, e = _find_class_range(lines)
    if s is None:
        print("  [!!] class _LibraryFilterDialog not found.")
        print("       Run edit_filter_ui.py's predecessor (the one that")
        print("       creates the filter dialog) first, or paste the")
        print("       current class body and I'll retarget.")
        sys.exit(1)

    print("  found class at line %d (%d lines)" % (s + 1, e - s))

    new_body = NEW_DIALOG.rstrip("\n").split("\n")
    new_lines = lines[:s] + new_body + lines[e:]
    new_src = "\n".join(new_lines)

    backup = path + ".bak_filterui"
    shutil.copy(path, backup)
    print("  backup ->", backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)

    try:
        py_compile.compile(path, doraise=True)
        print("  syntax OK")
    except py_compile.PyCompileError as ex:
        shutil.copy(backup, path)
        print("  ! syntax error — restored from backup")
        print(ex)
        sys.exit(1)

    print()
    print("Done.  The filter dialog now has:")
    print("  - a search bar at the top")
    print("  - Expand All / Collapse All buttons")
    print("  - the same checkbox tree as before")
    print()
    print("Search matches any token against the full category path;")
    print("ancestors stay visible so you keep context.")


if __name__ == "__main__":
    main()