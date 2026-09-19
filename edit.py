#!/usr/bin/env python3
"""
force_route_patch.py — replace collect_from_module and VERIFY the write.

Earlier attempts printed "syntax OK" but the routing line never made
it into the file.  This script reads back what it wrote and searches
for the routing line before declaring success.

If verification fails, it restores from backup.

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


NEW_COLLECT = r'''def collect_from_module(cat, mod_path, seen_names, specs_out, limit,
                        deep_c=False):
    if len(specs_out) >= limit:
        return 0
    if _DEBUG:
        print("[debug] collect %-45s cat=%s" % (mod_path, cat))
    mod = _safe_import(mod_path)
    if mod is None:
        if _DEBUG:
            print("[debug]   import failed")
        return 0

    exc_only = mod_path in _EXCEPTIONS_ONLY_ROOTS

    if _is_c_extension(mod_path):
        if _DEBUG:
            print("[debug]   -> C-extension path")
        n = _collect_from_c_extension(
            mod, mod_path, cat, seen_names, specs_out, limit,
            exc_only, deep=deep_c)
        if _DEBUG:
            print("[debug]   collected %d" % n)
        return n

    top_level = "." not in mod_path
    root = mod_path.split(".")[0]
    real_root = getattr(mod, "__name__", root).split(".")[0]
    roots = {root, real_root}
    added = 0
    for name in dir(mod):
        if len(specs_out) >= limit:
            break
        if name.startswith("_"):
            continue
        if name in seen_names:
            continue
        try:
            obj = getattr(mod, name)
        except BaseException:
            continue
        if not (inspect.isclass(obj) or inspect.isroutine(obj)):
            continue

        real_mod = getattr(obj, "__module__", "") or ""

        if not top_level:
            if real_mod and not any(real_mod.startswith(r)
                                    for r in roots):
                if _DEBUG:
                    print("[debug]   drop %-30s __module__=%r"
                          % (name, real_mod))
                continue

        # Route to the object's own module so a class found via a
        # shallow re-export lands under its real home.  Prefix is
        # taken from cat's first segment so the casing stays
        # consistent with the walker.
        spec_cat = cat
        if (real_mod
                and real_mod != mod_path
                and not real_mod.startswith("sip")
                and not real_mod.startswith("PyQt5.sip")
                and "." in real_mod
                and any(real_mod.startswith(r) for r in roots)):
            spec_cat = module_to_category(cat.split("/")[0], real_mod)
            if _DEBUG:
                print("[debug]   route %-24s -> %s"
                      % (name, spec_cat))

        is_exc = _is_exception_class(obj)
        if exc_only and not is_exc:
            continue

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
        if _DEBUG:
            print("[debug]     + %-30s (cat=%s)" % (name, spec_cat))

    if _DEBUG:
        print("[debug]   collected %d" % added)
    return added
'''


VERIFY_MARKERS = [
    "module_to_category(cat.split(\"/\")[0], real_mod)",
    "spec_cat = cat",
]


def _find_node(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def main():
    if not os.path.isfile(PATH):
        print("create.py not found.")
        sys.exit(1)

    with open(PATH, "r", encoding="utf-8") as f:
        original = f.read()

    tree = ast.parse(original)
    cm = _find_node(tree, "collect_from_module")
    if cm is None:
        print("! collect_from_module not found")
        sys.exit(1)

    start = cm.lineno - 1
    if cm.decorator_list:
        start = cm.decorator_list[0].lineno - 1
    end = cm.end_lineno

    lines = original.split("\n")
    new_lines = NEW_COLLECT.rstrip("\n").split("\n")
    candidate = "\n".join(lines[:start] + new_lines + lines[end:])

    # Parse the candidate before writing.
    try:
        ast.parse(candidate)
    except SyntaxError as e:
        print("! candidate does not parse:", e)
        sys.exit(1)

    # Backup, write, then READ BACK.
    backup = PATH + ".bak_force"
    shutil.copy(PATH, backup)
    print("  backup ->", backup)

    with open(PATH, "w", encoding="utf-8") as f:
        f.write(candidate)

    with open(PATH, "r", encoding="utf-8") as f:
        written = f.read()

    # Verify the routing line actually landed.
    missing = [m for m in VERIFY_MARKERS if m not in written]
    if missing:
        print("! VERIFY FAILED — restore from backup")
        for m in missing:
            print("    missing:", m)
        shutil.copy(backup, PATH)
        sys.exit(1)

    print("  write verified: routing line is present in collect_from_module")

    # Re-parse and compile.
    try:
        ast.parse(written)
    except SyntaxError as e:
        print("! syntax error after write:", e)
        shutil.copy(backup, PATH)
        sys.exit(1)

    try:
        py_compile.compile(PATH, doraise=True)
        print("  syntax OK")
    except py_compile.PyCompileError as e:
        shutil.copy(backup, PATH)
        print("! compile error — restored")
        print(e)
        sys.exit(1)

    # Show the actual routing lines, so we can see them.
    tree2 = ast.parse(written)
    cm2 = _find_node(tree2, "collect_from_module")
    print()
    print("Lines in the new collect_from_module mentioning routing:")
    body = written.split("\n")[cm2.lineno - 1:cm2.end_lineno]
    for i, line in enumerate(body, cm2.lineno):
        if "module_to_category" in line or "spec_cat = cat" in line \
                or "spec_cat = real_mod" in line:
            print("  %5d  %s" % (i, line))

    print()
    print("=" * 62)
    print("Rebuild:")
    print("    rm main.db")
    print("    bash build.sh")
    print()
    print("Verify:")
    print("    python3 -c \"import sqlite3; c=sqlite3.connect('main.db');")
    print("      print('lowercase torch/:', c.execute(")
    print("        \\\"SELECT COUNT(*) FROM nodes WHERE category LIKE 'torch/%'\\\"")
    print("        ).fetchone()[0])\"")


if __name__ == "__main__":
    main()
