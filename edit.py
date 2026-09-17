#!/usr/bin/env python3
"""
fix_create_db_format.py — repair emit_db's HEADER_LOADER.format() call.

The previous fix script checked whether the string
"header = (HEADER_LOADER" existed anywhere in create.py.  After
patching emit_json, that string appeared in the file, so the check
for emit_db falsely returned "already patched" and skipped the
second replacement.  Result: emit_db still calls

    HEADER_LOADER.format(...)

and crashes with KeyError on the first `{` inside _load_specs's
dict literals.

This script finds the remaining HEADER_LOADER.format(...) call by
line, verifies it's inside emit_db, and replaces the whole call with
a .replace() chain.

Idempotent.  Backs up create.py to create.py.bak_db_fmt.
"""

import os
import re
import shutil
import py_compile
import sys


def _find_create():
    for p in ("create.py",):
        if os.path.isfile(p):
            return p
    return None


def _patch(src):
    if '.replace("{data_file}", db_path)' in src:
        return src, 0

    lines = src.split("\n")

    # Locate emit_db.
    fn_start = None
    for i, ln in enumerate(lines):
        if re.match(r'^def\s+emit_db\s*\(', ln):
            fn_start = i
            break
    if fn_start is None:
        return src, 0

    # Function body range.
    fn_end = len(lines)
    for j in range(fn_start + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        if not ln.startswith(" ") and not ln.startswith("\t"):
            fn_end = j
            break

    # Find the line containing HEADER_LOADER.format( inside emit_db.
    bs = None
    for k in range(fn_start, fn_end):
        if ("HEADER_LOADER.format(" in lines[k]
                and ".replace(" not in lines[k]):
            bs = k
            break
    if bs is None:
        return src, 0

    # Find the matching close: first line whose stripped content is "))".
    be = None
    for k in range(bs, fn_end):
        if lines[k].strip() == "))":
            be = k + 1
            break
    if be is None:
        return src, 0

    indent = re.match(r'^(\s*)', lines[bs]).group(1)

    # Build the replacement block.
    repl = [
        indent + "_hdr = (HEADER_LOADER",
        indent + '        .replace("{json_path!r}", repr(JSON_FILE))',
        indent + '        .replace("{db_path!r}", repr(db_path))',
        indent + '        .replace("{data_file}", db_path)',
        indent + '        .replace("{data_format}", "db")',
        indent + '        .replace("{version}", torch_version)',
        indent + '        .replace("{torch_path}", torch_path)',
        indent + '        .replace("{date}", date)',
        indent + '        .replace("{node_count}", str(len(specs))))',
        indent + "f.write(_hdr)",
    ]

    new_lines = lines[:bs] + repl + lines[be:]
    return "\n".join(new_lines), 1


def main():
    path = _find_create()
    if not path:
        print("Could not find create.py")
        sys.exit(1)

    print("Target:", path)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if '.replace("{data_file}", db_path)' in src:
        print("  [ok] emit_db already uses .replace()")
        return

    new_src, n = _patch(src)
    if not n:
        print("  [!!] could not find the HEADER_LOADER.format() call")
        print("       inside emit_db.  Show me the current emit_db body")
        print("       and I'll retarget.")
        sys.exit(1)

    print("  [+] emit_db .format() call replaced with .replace() chain")

    backup = path + ".bak_db_fmt"
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
    print("Verify both emit_json and emit_db no longer call .format():")
    print("    grep -n 'HEADER_LOADER.format' create.py")
    print("Should print nothing.")
    print()
    print("Then regenerate:")
    print("    python create.py -l '[os,io,os.path,math,random,json,"
          "pathlib,shutil,tempfile,time,datetime,sqlite3,transformers,"
          "torchaudio,torchvision,matplotlib,numpy,scipy,pyautogui]' --db")
    print("    python main.py")


if __name__ == "__main__":
    main()