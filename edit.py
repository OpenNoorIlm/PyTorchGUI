#!/usr/bin/env python3
"""
edit.py — install the per-node widget host onto Nodes.py.

Adds one line to the end of Nodes.py that imports NodeClasses and
calls install(Node, NodeSocket).  Nothing else is touched.
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


INSTALL_BLOCK = '''

# ============================================================== #
#  Per-node widget host                                          #
# ============================================================== #

def _install_nodehost():
    try:
        try:
            from helpers.Nodes import NodeClasses as NC
        except ImportError:
            import NodeClasses as NC
        NC.install(Node, NodeSocket)
    except Exception as _ex:
        import traceback
        print("[nodehost] install failed:")
        traceback.print_exc()

_install_nodehost()
'''


def main():
    path = _find_nodes()
    if not path:
        print("Could not find helpers/Nodes/Nodes.py or Nodes.py")
        sys.exit(1)

    nc_path = None
    for p in ("helpers/Nodes/NodeClasses.py", "NodeClasses.py"):
        if os.path.isfile(p):
            nc_path = p
            break
    if not nc_path:
        print("! NodeClasses.py not found next to Nodes.py.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if "_install_nodehost" in src:
        print("  [ok] nodehost install already present")
        return

    # Ensure the trailing `if __name__ == "__main__":` block stays
    # at the very bottom by inserting *before* it.
    marker = 'if __name__ == "__main__":'
    idx = src.rfind(marker)
    if idx == -1:
        # no main block, append at end
        src = src.rstrip() + "\n" + INSTALL_BLOCK
    else:
        # back up to the line that starts the block
        line_start = src.rfind("\n", 0, idx) + 1
        src = src[:line_start] + INSTALL_BLOCK + "\n" + src[line_start:]

    backup = path + ".bak_nodehost"
    shutil.copy(path, backup)
    print("  backup ->", backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    try:
        py_compile.compile(path, doraise=True)
        print("  syntax OK")
    except py_compile.PyCompileError as e:
        shutil.copy(backup, path)
        print("  ! syntax error — restored from backup")
        print(e)
        sys.exit(1)

    print()
    print("Now run:")
    print("    python main.py")
    print()
    print("You should see:  [nodehost] installed on Node and NodeSocket")
    print("and [nodeclass] load messages (if you registered any classes).")


if __name__ == "__main__":
    main()