#!/usr/bin/env python3
"""
update_logo_v2.py — point every logo reference in the repo at the
live docs/banner.png on GitHub.

Files touched:

  1.  README.md      — inserts a centred banner at the top
  2.  initiate.py    — patches the README template it writes, so
                       regenerating README.md later keeps the banner
  3.  main.py        — fetches the banner and applies it as the
                       window icon at startup
  4.  Any *.md in the root or docs/ that has a bare "PyTorchUI" title
      and no banner — the script adds the banner block after the
      first heading.

Idempotent: running it twice is harmless.  Every file it edits is
backed up as <name>.bak_logo.

Run:
    python3 edit.py
    python main.py
"""

import glob
import os
import re
import shutil
import py_compile
import sys


RAW_URL = ("https://raw.githubusercontent.com/"
           "OpenNoorIlm/PyTorchUI/main/docs/banner.png")

BANNER_HTML = (
    '<p align="center">\n'
    '  <img src="%s" alt="PyTorchUI" width="720">\n'
    '</p>\n' % RAW_URL
)

BANNER_MD = (
    '<p align="center">\n'
    '  <img src="%s" alt="PyTorchUI" width="720">\n'
    '</p>\n' % RAW_URL
)


# ================================================================== #
#  helpers                                                            #
# ================================================================== #

def _insert_banner_into_markdown(src, banner):
    """Insert the banner after the first # heading, or at the top."""
    if RAW_URL in src:
        return src, "already present"

    # Replace an existing banner block if one exists.
    pattern = re.compile(
        r'<p align="center">\s*<img src="[^"]*banner[^"]*"[^>]*>\s*'
        r'</p>\n?',
        re.IGNORECASE)
    if pattern.search(src):
        new = pattern.sub(banner, src, count=1)
        return new, "replaced existing banner"

    lines = src.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            insert_at = i + 1
            if insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break
    else:
        insert_at = 0

    lines.insert(insert_at, "\n" + banner + "\n")
    return "".join(lines), "inserted banner"


def _replace_module_const(src, name, value):
    """Rewrite a module-level NAME = "..." or NAME = '...' assignment."""
    pattern = re.compile(
        r'^(' + re.escape(name) + r'\s*=\s*)'
        r'(?:"""[^"]*"""|\'\'\'[^\']*\'\'\'|"[^"]*"|\'[^\']*\')',
        re.MULTILINE)
    if pattern.search(src):
        return pattern.sub(r'\1"%s"' % value, src, count=1), True
    return src, False


# ================================================================== #
#  1. README.md                                                       #
# ================================================================== #

def patch_readme(path):
    if not os.path.isfile(path):
        return "not present"
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    new, status = _insert_banner_into_markdown(src, BANNER_MD)
    if new == src:
        return status
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return status


# ================================================================== #
#  2. main.py — fetch and set the window icon                         #
# ================================================================== #

LOADER_BLOCK = '''\

# ---------------------------------------------------------------- #
#  Remote logo                                                    #
# ---------------------------------------------------------------- #

_LOGO_URL = ("https://raw.githubusercontent.com/"
             "OpenNoorIlm/PyTorchUI/main/docs/banner.png")


def _fetch_and_set_window_icon(window):
    """Fetch the banner PNG and apply it as the window icon.

    QIcon cannot load from a URL, so we download the bytes with
    QNetworkAccessManager, build a QPixmap from them, and set that
    as the icon.  Fails silently on network problems.
    """
    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QPixmap, QIcon
        from PyQt5.QtNetwork import (QNetworkAccessManager,
                                     QNetworkRequest)
    except Exception as ex:
        print("[logo] QtNetwork unavailable:", ex)
        return

    mgr = QNetworkAccessManager(window)
    req = QNetworkRequest(QUrl(_LOGO_URL))
    try:
        req.setAttribute(
            QNetworkRequest.FollowRedirectsAttribute, True)
    except Exception:
        pass
    reply = mgr.get(req)

    def _on_finished():
        try:
            data = bytes(reply.readAll())
            pm = QPixmap()
            if pm.loadFromData(data):
                window.setWindowIcon(QIcon(pm))
                print("[logo] window icon set from remote banner")
            else:
                print("[logo] could not decode image data")
        except Exception as ex:
            print("[logo] apply failed:", ex)
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass

    reply.finished.connect(_on_finished)


def _install_remote_logo(api):
    """Schedule the icon fetch once the window is shown."""
    try:
        from PyQt5.QtCore import QTimer
        win = api.window
        QTimer.singleShot(50, lambda: _fetch_and_set_window_icon(win))
    except Exception as ex:
        print("[logo] schedule failed:", ex)

'''


def patch_main(path):
    if not os.path.isfile(path):
        return "not present"
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if "_install_remote_logo" in src:
        return "already patched"

    # Insert the helper block just before the final __main__ block.
    marker = 'if __name__ == "__main__":'
    idx = src.rfind(marker)
    if idx < 0:
        return "anchor: __main__ block not found"
    src = src[:idx] + LOADER_BLOCK + "\n" + src[idx:]

    # Hook it in after the first .show() call.
    if "def main():" in src and "win.show()" in src:
        m = re.search(
            r'(def main\(\):.*?)(\n\s*win\.show\(\))', src, re.DOTALL)
        if m:
            insert_at = m.end(2)
            src = (src[:insert_at]
                   + "\n    _install_remote_logo(api)"
                   + src[insert_at:])
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            return "patched (main)"

    m = re.search(r'^(\s*)api\.show\(\).*$', src, re.MULTILINE)
    if m:
        indent = m.group(1)
        insert_at = m.end()
        src = (src[:insert_at]
               + "\n%s_install_remote_logo(api)" % indent
               + src[insert_at:])
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        return "patched (fallback)"

    return "anchor: no api.show() call found"


# ================================================================== #
#  3. initiate.py — patch its README template                         #
# ================================================================== #

OLD_README_HEAD = '''\
README = \'\'\'\\
# PyTorchUI

A Blender-styled node editor for building and running PyTorch pipelines
visually. Drag nodes onto a canvas, wire them together, and press **Run**
to execute the generated Python.

![status](https://img.shields.io/badge/status-alpha-orange)
'''

NEW_README_HEAD = '''\
README = \'\'\'\\
# PyTorchUI

<p align="center">
  <img src="https://raw.githubusercontent.com/OpenNoorIlm/PyTorchUI/main/docs/banner.png" alt="PyTorchUI" width="720">
</p>

A Blender-styled node editor for building and running PyTorch pipelines
visually. Drag nodes onto a canvas, wire them together, and press **Run**
to execute the generated Python.

![status](https://img.shields.io/badge/status-alpha-orange)
'''


def patch_initiate(path):
    if not os.path.isfile(path):
        return "not present"
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if RAW_URL in src:
        return "already present"
    if OLD_README_HEAD not in src:
        return "anchor: README template head not found"
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(OLD_README_HEAD, NEW_README_HEAD, 1))
    return "patched"


# ================================================================== #
#  4. Every other .md in the repo                                     #
# ================================================================== #

SKIP_MD = {
    "README.md",          # handled above
    "CODE_OF_CONDUCT.md", # boilerplate, no banner wanted
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
}


def patch_other_markdowns():
    touched = []
    for pattern in ("*.md", "docs/*.md", "examples/*.md"):
        for path in sorted(glob.glob(pattern)):
            if os.path.basename(path) in SKIP_MD:
                continue
            # only touch files that actually have a top-level heading
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            if not src.lstrip().startswith("# "):
                continue
            new, status = _insert_banner_into_markdown(src, BANNER_MD)
            if new != src:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                touched.append((path, status))
    return touched


# ================================================================== #
#  driver                                                             #
# ================================================================== #

def main():
    touched_files = []

    print("README.md:")
    s = patch_readme("README.md")
    print("  %s" % s)
    if s not in ("not present", "already present"):
        touched_files.append("README.md")

    print("main.py:")
    s = patch_main("main.py")
    print("  %s" % s)
    if s.startswith("patched"):
        touched_files.append("main.py")

    print("initiate.py:")
    s = patch_initiate("initiate.py")
    print("  %s" % s)
    if s == "patched":
        touched_files.append("initiate.py")

    print("other markdown files:")
    others = patch_other_markdowns()
    if not others:
        print("  (none)")
    else:
        for path, status in others:
            print("  %-30s %s" % (path, status))
            touched_files.append(path)

    if not touched_files:
        print()
        print("Nothing to do.")
        return

    for path in touched_files:
        shutil.copy(path, path + ".bak_logo")
        print("  backup -> %s.bak_logo" % path)

    # Syntax check the Python files we touched.
    for path in ("main.py", "initiate.py"):
        if path in touched_files:
            try:
                py_compile.compile(path, doraise=True)
                print("  %s syntax OK" % path)
            except py_compile.PyCompileError as e:
                shutil.copy(path + ".bak_logo", path)
                print("  ! %s syntax error — restored" % path)
                print(e)
                sys.exit(1)

    print()
    print("Done.  Next:")
    print("  1. Confirm docs/banner.png is committed and pushed:")
    print("       curl -I %s" % RAW_URL)
    print("     Look for HTTP 200 and content-type: image/png.")
    print("  2. python main.py")
    print("  3. Open the GitHub repo page — the README should show")
    print("     the banner.")


if __name__ == "__main__":
    main()