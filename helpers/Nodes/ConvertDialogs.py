"""
ConvertDialogs.py — two-way converters between Python projects and
PyTorchUI graphs.

Both dialogs preserve the source folder structure: the source folder
is copied verbatim to the destination, then each eligible file in the
copy gets a converted sibling.

  PythonToPyUIDialog
      Source: a Python project folder.
      For each .py, writes a sibling .py.json with imports, classes,
      functions and docstrings.

  PyUIToPythonDialog
      Source: a folder containing PyTorchUI graph JSON files.
      For each graph .json, writes a sibling .py that runs the graph
      via the PyTorchUI runtime.

No source file is ever modified.  Destination must not already
exist (refuses to overwrite).
"""

import ast
import json
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QPlainTextEdit, QMessageBox,
    QFileDialog, QProgressBar,
)


SKIP_PATTERNS = (
    ".venv", "venv", "env", "ENV",
    "__pycache__", ".git",
    "build", "dist", ".eggs",
    "node_modules", ".mypy_cache", ".pytest_cache",
)


def _name_of(node):
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return _name_of(node.value) + "." + node.attr
        return "?"


def summarize_python_file(path):
    """Return a JSON-friendly summary of one .py file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as ex:
        return {"source": os.path.basename(path),
                "error": "read failed: %s" % ex}

    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as ex:
        return {"source": os.path.basename(path),
                "error": "syntax error: %s" % ex}

    imports = []
    from_imports = []
    classes = []
    functions = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            from_imports.append({
                "module": node.module or "",
                "level": node.level or 0,
                "names": [a.name for a in node.names],
            })
        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "bases": [_name_of(b) for b in node.bases],
                "doc": ast.get_docstring(node) or "",
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            functions.append({
                "name": node.name,
                "args": args,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "doc": ast.get_docstring(node) or "",
            })

    return {
        "source": os.path.basename(path),
        "imports": imports,
        "from_imports": from_imports,
        "classes": classes,
        "functions": functions,
        "node_count": len(classes) + len(functions),
    }


def _ignore_patterns():
    return shutil.ignore_patterns(*SKIP_PATTERNS)


class _BaseConvertDialog(QDialog):
    """Common scaffolding: paths, skip toggle, log, progress, buttons."""

    title = "Convert"
    subtitle = ""
    ok_label = "Convert"

    def __init__(self, parent=None, src_label="Source:",
                 src_placeholder="", src_is_folder=True):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.setModal(True)
        self.resize(720, 560)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)

        head = QLabel(self.title)
        head.setStyleSheet("font-weight:600;color:#F0F0F0;font-size:13px;")
        v.addWidget(head)

        if self.subtitle:
            sub = QLabel(self.subtitle)
            sub.setStyleSheet("color:#8A8A8A;font-size:11px;")
            sub.setWordWrap(True)
            v.addWidget(sub)

        row = QHBoxLayout()
        row.addWidget(QLabel(src_label))
        self.edit_src = QLineEdit()
        self.edit_src.setPlaceholderText(src_placeholder)
        row.addWidget(self.edit_src, 1)
        b1 = QPushButton("Browse\u2026")
        b1.clicked.connect(
            lambda: self._pick(self.edit_src, src_is_folder))
        row.addWidget(b1)
        v.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Dest:  "))
        self.edit_dst = QLineEdit()
        self.edit_dst.setPlaceholderText("Output folder (must not exist)")
        row.addWidget(self.edit_dst, 1)
        b2 = QPushButton("Browse\u2026")
        b2.clicked.connect(lambda: self._pick(self.edit_dst, True))
        row.addWidget(b2)
        v.addLayout(row)

        self.chk_skip = QCheckBox(
            "Skip .venv, __pycache__, .git, build, dist, node_modules")
        self.chk_skip.setChecked(True)
        v.addWidget(self.chk_skip)

        v.addWidget(QLabel("Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "QPlainTextEdit{background:#141414;color:#DDD;"
            " border:1px solid #2A2A2A;padding:6px;"
            " font-family:'JetBrains Mono','Consolas',monospace;"
            " font-size:11px;}")
        v.addWidget(self.log, 1)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        v.addWidget(self.bar)

        row = QHBoxLayout()
        row.addStretch(1)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_cancel)
        self.b_go = QPushButton(self.ok_label)
        self.b_go.setDefault(True)
        self.b_go.clicked.connect(self._run)
        row.addWidget(self.b_go)
        v.addLayout(row)

    def _pick(self, edit, folder):
        start = edit.text() or os.path.expanduser("~")
        if folder:
            p = QFileDialog.getExistingDirectory(
                self, "Choose folder", start)
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "Choose file", start, "All Files (*)")
        if p:
            edit.setText(p)

    def _log(self, line):
        self.log.appendPlainText(str(line))
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
        QApplication.processEvents()

    def _validate_paths(self):
        src = self.edit_src.text().strip()
        dst = self.edit_dst.text().strip()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, self.title, "Source folder missing.")
            return None, None
        if not dst:
            QMessageBox.warning(self, self.title, "Destination is empty.")
            return None, None
        if os.path.abspath(src) == os.path.abspath(dst):
            QMessageBox.warning(
                self, self.title,
                "Source and destination are the same folder.")
            return None, None
        if os.path.exists(dst):
            QMessageBox.warning(
                self, self.title,
                "Destination already exists:\n  %s\n\n"
                "Choose a new folder or delete it first." % dst)
            return None, None
        return src, dst

    def _copy_tree(self, src, dst):
        ignore = _ignore_patterns() if self.chk_skip.isChecked() else None
        self._log("copying tree  %s -> %s" % (src, dst))
        try:
            shutil.copytree(src, dst, ignore=ignore)
            self._log("  ok")
            return True
        except Exception as ex:
            self._log("  ! copy failed: %s" % ex)
            return False

    def _walk(self, root, ext):
        out = []
        for dirpath, dirs, files in os.walk(root):
            for f in files:
                if f.endswith(ext):
                    out.append(os.path.join(dirpath, f))
        out.sort()
        return out

    def _run(self):
        pass  # overridden by subclasses


class PythonToPyUIDialog(_BaseConvertDialog):

    title = "Convert Python \u2192 PyTorchUI"
    subtitle = (
        "Copies the whole project to the destination, then writes a "
        ".py.json summary next to each .py file.  The source is never "
        "modified.")
    ok_label = "Convert"

    def __init__(self, parent=None):
        super().__init__(
            parent,
            src_label="Source:",
            src_placeholder="Python project folder",
            src_is_folder=True)

    def _run(self):
        src, dst = self._validate_paths()
        if not src:
            return

        self.log.clear()
        self._log("# Python \u2192 PyTorchUI")
        self._log("# source: %s" % src)
        self._log("# dest:   %s" % dst)
        self._log("")

        if not self._copy_tree(src, dst):
            return

        py_files = self._walk(dst, ".py")
        self._log("")
        self._log("converting %d .py file(s)" % len(py_files))
        self.bar.setRange(0, max(1, len(py_files)))

        total_nodes = 0
        total_written = 0
        for i, p in enumerate(py_files, 1):
            self.bar.setValue(i)
            rel = os.path.relpath(p, dst)
            summary = summarize_python_file(p)
            out = p + ".json"
            try:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2)
                total_written += 1
                total_nodes += summary.get("node_count", 0)
                err = summary.get("error", "")
                suffix = ("  (%s)" % err) if err else ""
                self._log("  %s -> %s%s"
                          % (rel, os.path.basename(out), suffix))
            except Exception as ex:
                self._log("  ! write failed for %s: %s" % (out, ex))

        self._log("")
        self._log("done.  %d .py.json, %d class/function summaries."
                  % (total_written, total_nodes))
        QMessageBox.information(
            self, self.title,
            "Wrote %d .py.json file(s) to:\n  %s"
            % (total_written, dst))
        self.accept()


class PyUIToPythonDialog(_BaseConvertDialog):

    title = "Convert PyTorchUI \u2192 Python"
    subtitle = (
        "Copies the whole folder to the destination, then writes a "
        ".py next to each PyTorchUI graph .json.  Folder structure is "
        "preserved.")
    ok_label = "Convert"

    def __init__(self, parent=None, code_provider=None):
        self._code_provider = code_provider
        super().__init__(
            parent,
            src_label="Source:",
            src_placeholder="Folder containing graph .json files",
            src_is_folder=True)

    def _is_graph(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return False
        return (isinstance(d, dict)
                and "nodes" in d and "edges" in d
                and isinstance(d.get("nodes"), list))

    def _run(self):
        src, dst = self._validate_paths()
        if not src:
            return

        self.log.clear()
        self._log("# PyTorchUI \u2192 Python")
        self._log("# source: %s" % src)
        self._log("# dest:   %s" % dst)
        self._log("")

        if not self._copy_tree(src, dst):
            return

        json_files = self._walk(dst, ".json")
        graphs = [p for p in json_files if self._is_graph(p)]
        self._log("")
        self._log("found %d graph file(s) of %d .json"
                  % (len(graphs), len(json_files)))

        if not graphs:
            self._log("nothing to convert.")
            QMessageBox.information(
                self, self.title,
                "No PyTorchUI graph files found.")
            self.accept()
            return

        if self._code_provider is None:
            self._log("! no code provider was passed to the dialog")
            return

        self.bar.setRange(0, len(graphs))
        written = 0
        for i, p in enumerate(graphs, 1):
            self.bar.setValue(i)
            rel = os.path.relpath(p, dst)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as ex:
                self._log("  ! read %s: %s" % (rel, ex))
                continue
            try:
                code = self._code_provider(d)
            except Exception as ex:
                self._log("  ! codegen %s: %s" % (rel, ex))
                continue
            out = os.path.splitext(p)[0] + ".py"
            try:
                with open(out, "w", encoding="utf-8") as f:
                    f.write(code)
                written += 1
                self._log("  %s -> %s" % (rel, os.path.basename(out)))
            except Exception as ex:
                self._log("  ! write %s: %s" % (out, ex))

        self._log("")
        self._log("done.  %d .py file(s)." % written)
        QMessageBox.information(
            self, self.title,
            "Wrote %d .py file(s) to:\n  %s" % (written, dst))
        self.accept()
