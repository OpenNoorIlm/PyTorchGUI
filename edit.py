#!/usr/bin/env python3
"""
fix_qts_aggregator.py — route C-extension objects to their real home.

PyQt5.Qt re-exports the entire Qt API from QtCore, QtGui, QtWidgets,
etc.  Because it is walked first (alphabetically), it steals every
name and marks them seen, so the real modules find nothing to add.

Fix: inside _collect_from_c_extension, look at obj.__module__.  If it
points to a specific PyQt5.* submodule, use that for the category
instead of the walker's assignment.  So a QObject found via PyQt5.Qt
still ends up under PyQt5/QtCore.

Run:
    python3 edit.py
    rm main.db
    bash build.sh
"""

import ast
import os
import shutil
import py_compile
import sys


PATH = "create.py"


NEW_COLLECT_CEXT = '''\
def _collect_from_c_extension(mod, mod_path, cat, seen_names,
                              specs_out, limit, exc_only, deep=False):
    """Enumerate classes and functions from a compiled extension.

    Re-exports are a real problem: PyQt5.Qt contains the whole Qt
    API copied from QtCore, QtGui, etc.  We route each object to the
    category named by its own __module__ when that points to a
    specific PyQt5.* submodule, so QObject lands under PyQt5/QtCore
    even when discovered via PyQt5.Qt.
    """
    added = 0
    try:
        members = list(vars(mod).items())
    except Exception:
        members = []

    for name, obj in members:
        if len(specs_out) >= limit:
            break
        if name.startswith("_"):
            continue
        if name in seen_names:
            continue
        if not (inspect.isclass(obj) or inspect.isroutine(obj)):
            continue

        is_exc = _is_exception_class(obj)
        if exc_only and not is_exc:
            continue

        # ---- category routing ---- #
        # Prefer the object's own __module__ when it points to a
        # specific module inside the same package.  Ignore SIP
        # placeholders and the empty string.
        spec_cat = cat
        real_mod = getattr(obj, "__module__", None) or ""
        if (real_mod
                and real_mod != mod_path
                and "." in real_mod
                and not real_mod.startswith("sip")
                and not real_mod.startswith("PyQt5.sip")):
            spec_cat = real_mod.replace(".", "/")

        seen_names.add(name)

        if is_exc:
            spec_cat = EXCEPTIONS_CATEGORY
            qualname = _exception_qualname(obj, name)
        else:
            qualname = None

        spec = {
            "name":        name,
            "color":       color_for(spec_cat),
            "category":    spec_cat,
            "description": get_doc(obj),
            "qualname":    qualname,
            "inputs":      get_params(obj),
            "outputs":     [(name, "object",
                             "Result of %s.%s" % (mod_path, name))],
            "full_path":   "%s.%s" % (mod_path, name),
        }

        _nc = _node_class_for(mod_path, name)
        if _nc:
            spec["node_class"] = _nc

        specs_out.append(spec)
        added += 1

        if deep and inspect.isclass(obj) and len(specs_out) < limit:
            try:
                inner = list(vars(obj).items())
            except Exception:
                inner = []
            for inner_name, inner_obj in inner:
                if inner_name.startswith("_"):
                    continue
                full_inner = "%s.%s" % (name, inner_name)
                if full_inner in seen_names:
                    continue
                if not (inspect.isclass(inner_obj)
                        or inspect.isroutine(inner_obj)):
                    continue
                seen_names.add(full_inner)
                sub = {
                    "name":        full_inner,
                    "color":       color_for(spec_cat),
                    "category":    spec_cat,
                    "description": get_doc(inner_obj),
                    "qualname":    ("%s.%s" % (qualname, inner_name))
                                   if qualname else None,
                    "inputs":      get_params(inner_obj),
                    "outputs":     [(inner_name, "object",
                                     "Nested attribute of %s.%s"
                                     % (mod_path, name))],
                    "full_path":   "%s.%s.%s" % (mod_path, name, inner_name),
                }
                specs_out.append(sub)
                added += 1

    return added
'''


def _function_range(src, name):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            start = node.lineno - 1
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            return start, node.end_lineno
    return None


def replace_function(src, name, new_src):
    rng = _function_range(src, name)
    if rng is None:
        return src, False
    start, end = rng
    lines = src.split("\n")
    new_lines = new_src.rstrip("\n").split("\n")
    return "\n".join(lines[:start] + new_lines + lines[end:]), True


def main():
    if not os.path.isfile(PATH):
        print("create.py not found — run from the project root.")
        sys.exit(1)

    print("Target:", PATH)
    with open(PATH, "r", encoding="utf-8") as f:
        src = f.read()

    if "__module__ routing" in src or (
            'real_mod = getattr(obj, "__module__", None) or ""' in src
            and "spec_cat = real_mod.replace" in src):
        print("  [ok] already patched")
        return

    src, ok = replace_function(
        src, "_collect_from_c_extension", NEW_COLLECT_CEXT)
    print("  _collect_from_c_extension replaced:", ok)
    if not ok:
        print()
        print("Function not found — paste create.py.")
        sys.exit(1)

    backup = PATH + ".bak_qts"
    shutil.copy(PATH, backup)
    print("  backup ->", backup)

    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)

    try:
        py_compile.compile(PATH, doraise=True)
        print("  syntax OK")
    except py_compile.PyCompileError as e:
        shutil.copy(backup, PATH)
        print("  ! syntax error — restored")
        print(e)
        sys.exit(1)

    print()
    print("=" * 62)
    print("Now rebuild the DB from scratch:")
    print("=" * 62)
    print()
    print("    rm main.db")
    print("    bash build.sh")
    print()
    print("The 'rm main.db' is important — the append-only logic keeps")
    print("the 18606 rows already mis-categorised under PyQt5/Qt.  A")
    print("fresh build replaces them with correctly-routed rows.")
    print()
    print("After the build, verify:")
    print()
    print("    python3 -c \"import sqlite3; c=sqlite3.connect('main.db');"
          " [print(r) for r in c.execute('SELECT category, COUNT(*) "
          "FROM nodes WHERE category LIKE \\\"PyQt5/Qt%\\\" "
          "GROUP BY category ORDER BY 2 DESC LIMIT 15')]\"")
    print()
    print("Expected: PyQt5/QtCore, PyQt5/QtGui, PyQt5/QtWidgets each")
    print("with 100-400 nodes, and PyQt5/Qt with only a handful.")


if __name__ == "__main__":
    main()
