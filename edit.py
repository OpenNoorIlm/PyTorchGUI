#!/usr/bin/env python3
"""
fix_enum_defaults2.py — line-based retry of the enum-default fix.

The previous patch anchored on an exact multi-line string; the current
create.py has that block condensed onto one line:

    if p.default is inspect.Parameter.empty:
        desc, dv = "", None
    else:
        ...

This version locates get_params by its `def` line, finds the
`if p.default is inspect.Parameter.empty:` inside it, and replaces the
block through the closing `out.append(...)` line.

Idempotent.  Backs up create.py to create.py.bak_enum2.
"""

import os
import re
import shutil
import py_compile
import sys


def _find_create():
    for p in ("create.py", "helpers/create.py"):
        if os.path.isfile(p):
            return p
    return None


NEW_DEFAULT_BLOCK = '''\
        if p.default is inspect.Parameter.empty:
            desc, dv = "", None
        else:
            # A default is only usable if its repr() is a valid Python
            # literal.  Enums (AwqBackend.AUTO, etc.), tensors,
            # dataclasses, and custom objects all produce <...>-shaped
            # reprs that break the generated file.  We drop those.
            import enum as _enum

            def _is_literal_default(x):
                if x is None or isinstance(x, bool):
                    return True
                if isinstance(x, _enum.Enum):
                    return False
                if type(x) is int or type(x) is float:
                    return True
                if type(x) is str and len(x) < 200:
                    return True
                return False

            try:
                desc = "Default: %r" % (p.default,)
            except Exception:
                desc = "Has default"

            if not _is_literal_default(p.default):
                dv = None
            else:
                try:
                    r = repr(p.default)
                except Exception:
                    r = ""
                if (not r
                        or r.startswith("<")
                        or r.endswith(">")
                        or " object at 0x" in r):
                    dv = None
                elif isinstance(p.default, str):
                    dv = p.default
                else:
                    dv = r
'''


_DEF_RE = re.compile(r'^def\s+get_params\s*\(')
_EMPTY_RE = re.compile(r'^(\s*)if\s+p\.default\s+is\s+inspect\.Parameter\.empty\s*:')
_APPEND_RE = re.compile(r'^(\s*)out\.append\(')


def _find_get_params(lines):
    start = None
    for i, ln in enumerate(lines):
        if _DEF_RE.match(ln):
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if not ln.startswith(" ") and not ln.startswith("\t"):
            end = j
            break
    return start, end


def _find_block(lines, gs, ge):
    """
    Inside get_params[gs:ge], find the [block_start, block_end) that runs
    from the `if p.default is inspect.Parameter.empty:` line through the
    line BEFORE the first `out.append(...)` at the same indentation.
    """
    bs = None
    for i in range(gs, ge):
        if _EMPTY_RE.match(lines[i]):
            bs = i
            break
    if bs is None:
        return None, None

    # Same-indent `out.append(` is the terminator.
    indent = len(lines[bs]) - len(lines[bs].lstrip())
    be = None
    for j in range(bs + 1, ge):
        m = _APPEND_RE.match(lines[j])
        if not m:
            continue
        ind_j = len(m.group(1))
        if ind_j == indent:
            be = j
            break
    if be is None:
        return None, None
    return bs, be


def main():
    path = _find_create()
    if not path:
        print("Could not find create.py")
        sys.exit(1)

    print("Target:", path)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if "_is_literal_default" in src:
        print("  [ok] already patched")
        return

    lines = src.split("\n")
    gs, ge = _find_get_params(lines)
    if gs is None:
        print("  [!!] def get_params not found")
        sys.exit(1)
    print("  found get_params at line %d (%d lines)"
          % (gs + 1, ge - gs))

    bs, be = _find_block(lines, gs, ge)
    if bs is None:
        print("  [!!] could not find the default-handling block inside")
        print("       get_params.  Here is the current body:")
        for k in range(gs, ge):
            print("       %s" % lines[k])
        sys.exit(1)
    print("  found default block at lines %d-%d (%d lines)"
          % (bs + 1, be, be - bs))

    # Show the block we're about to replace so the user can verify.
    print("  current block:")
    for k in range(bs, be):
        print("    %s" % lines[k])

    new_lines = lines[:bs] + NEW_DEFAULT_BLOCK.rstrip("\n").split("\n") + lines[be:]
    new_src = "\n".join(new_lines)

    backup = path + ".bak_enum2"
    shutil.copy(path, backup)
    print()
    print("  backup -> %s" % backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)

    try:
        py_compile.compile(path, doraise=True)
        print("  syntax OK.  get_params default-handling block replaced.")
    except py_compile.PyCompileError as ex:
        shutil.copy(backup, path)
        print("  ! syntax error — restored from backup")
        print(ex)
        sys.exit(1)

    print()
    print("Verify the fix works with the offending default:")
    print("    python3 - <<'PY'")
    print("    import enum")
    print("    class AwqBackend(enum.Enum):")
    print("        AUTO = 'auto'")
    print("    print('repr:', repr(AwqBackend.AUTO))")
    print("    import enum as _e")
    print("    x = AwqBackend.AUTO")
    print("    print('is enum:', isinstance(x, _e.Enum))")
    print("    print('is int :', isinstance(x, int))")
    print("    PY")
    print()
    print("Then regenerate:")
    print("    python create.py -l '[os,io,os.path,math,random,json,"
          "pathlib,shutil,tempfile,time,datetime,sqlite3,transformers]'")
    print("    python main.py")


if __name__ == "__main__":
    main()