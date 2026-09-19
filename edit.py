#!/usr/bin/env python3
"""
add_loader_only.py — add a --loader-only flag to create.py.

Problem:
    `python create.py --db` walks every package (torch + libs) and
    takes ~5 minutes.  If you only need to regenerate main.py — the
    loader stub — you should not have to pay that cost.

Solution:
    --loader-only  reads metadata from the existing main.db (or
    main.json), skips the walk entirely, and re-emits main.py from
    the HEADER_LOADER template.  Runs in under a second.

Usage:
    python create.py --db --loader-only
    python create.py --json --loader-only

Idempotent.  Backs up create.py as create.py.bak_loadonly.

Run:
    python3 edit.py
    python create.py --db --loader-only
"""

import os
import re
import shutil
import py_compile
import sys


# ---- 1. add the helper functions just before def main(argv=None): ---- #

HELPERS = '''\
def _read_db_metadata(path):
    """Return the metadata table from a PyTorchUI db as a dict.

    Empty dict if the file is missing or malformed — the caller
    falls back to defaults.
    """
    if not os.path.isfile(path):
        return {}
    try:
        con = sqlite3.connect(path)
        try:
            rows = con.execute(
                "SELECT key, value FROM metadata").fetchall()
        finally:
            con.close()
        return {str(k): str(v) for k, v in rows}
    except Exception:
        return {}


def _read_json_metadata(path):
    """Return the top-level metadata from a PyTorchUI json dump."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return {
            "torch_version": str(d.get("torch_version", "n/a")),
            "torch_path":    str(d.get("torch_path", "n/a")),
            "node_count":    str(d.get("node_count", 0)),
        }
    except Exception:
        return {}


def emit_loader_only(out_file, data_file, data_format,
                     version, path, node_count,
                     json_path=None, db_path=None):
    """Emit just the loader main.py, no walking, no package imports.

    For format=db   the loader tries main.json first, then main.db.
    For format=json the loader tries the given json path, then the
                    default db path.
    """
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # The loader template already substitutes both fallback paths.
    # For db output, we leave the json fallback at its default.
    _json = json_path if json_path is not None else JSON_FILE
    _db   = db_path if db_path is not None else DB_FILE

    with open(out_file, "w", encoding="utf-8") as f:
        header = (HEADER_LOADER
                  .replace("{json_path!r}", repr(_json))
                  .replace("{db_path!r}",   repr(_db))
                  .replace("{data_file}",   data_file)
                  .replace("{data_format}", data_format)
                  .replace("{version}",     version)
                  .replace("{torch_path}",  path)
                  .replace("{date}",        date)
                  .replace("{node_count}",  str(node_count)))
        f.write(header)
        f.write(FOOTER)
    return out_file


'''


def patch_helpers(src):
    if "_read_db_metadata" in src:
        return src, "already present"
    anchor = "def main(argv=None):\n"
    if anchor not in src:
        return src, "anchor: 'def main(argv=None):' not found"
    return src.replace(anchor, HELPERS + anchor, 1), "inserted helpers"


# ---- 2. add --loader-only to the argument parser ---- #

OLD_ARG_TAIL = '''\
    p.add_argument(
        "--quiet", action="store_true",
        help="suppress progress output",
    )
    return p
'''

NEW_ARG_TAIL = '''\
    p.add_argument(
        "--quiet", action="store_true",
        help="suppress progress output",
    )
    p.add_argument(
        "--loader-only", dest="loader_only", action="store_true",
        help="skip the walk; only re-emit the loader main.py using "
             "metadata already present in main.db / main.json.  Fast.",
    )
    return p
'''


def patch_parser(src):
    if "--loader-only" in src:
        return src, "already present"
    if OLD_ARG_TAIL not in src:
        return src, "anchor: parser tail not found"
    return src.replace(OLD_ARG_TAIL, NEW_ARG_TAIL, 1), "inserted flag"


# ---- 3. handle the flag early in main() ---- #

OLD_MAIN_HEAD = '''\
def main(argv=None):
    warnings.filterwarnings("ignore")
    parser = _build_parser()
    args = parser.parse_args(argv)

    fmt = _resolve_format(args)
    cap_map = _parse_cap_libs(args.cap_libs)
'''

NEW_MAIN_HEAD = '''\
def main(argv=None):
    warnings.filterwarnings("ignore")
    parser = _build_parser()
    args = parser.parse_args(argv)

    fmt = _resolve_format(args)

    # ---- fast path: emit only the loader, no walk ---- #
    if getattr(args, "loader_only", False):
        if fmt == "py":
            print("! --loader-only requires --db or --json")
            sys.exit(2)

        # Read metadata from whichever data file we already have.
        meta = {}
        if fmt == "db":
            meta = _read_db_metadata(args.db_path)
            if not meta:
                meta = _read_json_metadata(args.json_path)
            data_file = args.db_path
            json_path = args.json_path
            db_path   = args.db_path
        else:
            meta = _read_json_metadata(args.json_path)
            if not meta:
                meta = _read_db_metadata(args.db_path)
            data_file = args.json_path
            json_path = args.json_path
            db_path   = args.db_path

        if not meta:
            print("! no existing %s found; run a full build first"
                  % (data_file,))
            sys.exit(1)

        version    = meta.get("torch_version", "n/a")
        path       = meta.get("torch_path",    "n/a")
        node_count = meta.get("node_count",    "0")

        emit_loader_only(
            out_file=args.out_file,
            data_file=data_file,
            data_format=fmt,
            version=version,
            path=path,
            node_count=node_count,
            json_path=json_path,
            db_path=db_path,
        )

        if not args.quiet:
            print("output format:", fmt, "(loader-only)")
            print("data file:    ", data_file)
            print("nodes:        ", node_count)
            print("Wrote", args.out_file)
        return

    cap_map = _parse_cap_libs(args.cap_libs)
'''


def patch_main_head(src):
    if 'getattr(args, "loader_only", False)' in src:
        return src, "already present"
    if OLD_MAIN_HEAD not in src:
        return src, "anchor: main() head not found"
    return src.replace(OLD_MAIN_HEAD, NEW_MAIN_HEAD, 1), "patched"


# ---- driver ---- #

def main():
    path = "create.py"
    if not os.path.isfile(path):
        print("create.py not found — run from the project root.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    original = src
    for label, fn in (
        ("helpers",     patch_helpers),
        ("parser flag", patch_parser),
        ("main() head", patch_main_head),
    ):
        src, status = fn(src)
        print("  %-12s %s" % (label, status))
        if "not found" in status:
            print()
            print("Anchor missing.  Nothing written.")
            sys.exit(1)

    if src == original:
        print()
        print("Nothing to do — create.py already up to date.")
        return

    backup = path + ".bak_loadonly"
    shutil.copy(path, backup)
    print("  backup -> %s" % backup)

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
    print("Done.  Try it:")
    print("    python create.py --db --loader-only")
    print()
    print("This reads metadata from the existing data/main.db (or")
    print("main.db), skips the package walk, and re-emits main.py")
    print("in under a second.")


if __name__ == "__main__":
    main()