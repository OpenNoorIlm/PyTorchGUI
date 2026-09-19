#!/usr/bin/env python3
"""
route_by_module.py — categorise objects by their real __module__.

Replaces collect_from_module with a version that, when a class or
function is discovered in a module that is not its definition site,
writes the row under the deeper module's category.

So torch.nn.Conv2d (discovered in torch.nn, defined in
torch.nn.modules.conv) is registered as:

    category  Torch/nn/modules/conv

instead of

    category  Torch/nn

The old behaviour:  the shallow module ate every name and marked it
seen, so the deep module found nothing left to add.  The new
behaviour:  the shallow module still walks first, but the row lands
where the class is actually defined.

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


# The full replacement.  Kept as one triple-quoted string with a
# plain r-prefix so backslashes in regexes are literal.

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

        # Keep only objects defined inside this package.  Objects
        # whose real module is unrelated (a helper imported from
        # somewhere else) are dropped.
        if not top_level:
            if real_mod and not any(real_mod.startswith(r)
                                    for r in roots):
                if _DEBUG:
                    print("[debug]   drop %-30s __module__=%r"
                          % (name, real_mod))
                continue

        # ---- the routing step ---- #
        # If the object's real module is a deeper path inside the
        # same package, categorise the node there instead of under
        # the module we happened to find it in.
        spec_cat = cat
        if (real_mod
                and real_mod != mod_path
                and not real_mod.startswith("sip")
                and not real_mod.startswith("PyQt5.sip")
                and "." in real_mod
                and any(real_mod.startswith(r) for r in roots)):
            spec_cat = real_mod.replace(".", "/")
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


def _function_range(src, name):
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print("  ! create.py does not parse: %s" % e)
        return None
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

    if "spec_cat = real_mod.replace" in src:
        print("  [ok] routing already present in collect_from_module")
        return

    new_src, ok = replace_function(src, "collect_from_module", NEW_COLLECT)
    print("  collect_from_module replaced:", ok)
    if not ok:
        print()
        print("Function not found — paste create.py and retarget.")
        sys.exit(1)

    # Verify the resulting file parses.
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("  ! new source does not parse: %s" % e)
        sys.exit(1)

    backup = PATH + ".bak_routing"
    shutil.copy(PATH, backup)
    print("  backup ->", backup)

    with open(PATH, "w", encoding="utf-8") as f:
        f.write(new_src)

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
    print("Rebuild from scratch:")
    print("=" * 62)
    print()
    print("    rm main.db")
    print("    bash build.sh")
    print()
    print("The rm is required — append-only would keep the existing")
    print("rows under their old categories.")
    print()
    print("After the build, verify with:")
    print()
    print("    python3 -c \"import sqlite3; c=sqlite3.connect('main.db');\\")
    print("      [print('%-46s %d' % r) for r in c.execute(\\")
    print("      'SELECT category, COUNT(*) FROM nodes \\")
    print("       WHERE category LIKE \\\"Torch/nn%\\\" \\")
    print("       GROUP BY category ORDER BY 2 DESC LIMIT 12')]\"")
    print()
    print("Expected: Torch/nn shrinks to a handful of torch-specific")
    print("helpers (ModuleList, Sequential, etc. defined in __init__),")
    print("and Torch/nn/modules/conv, .../linear, .../activation each")
    print("get their real counts.")


if __name__ == "__main__":
    main()
