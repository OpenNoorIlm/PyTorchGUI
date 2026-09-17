#!/usr/bin/env python3
"""
create.py — auto-generate main.py (or a data file plus loader) from the
installed Python package tree.

Usage:
    python create.py                             # embed specs in main.py
    python create.py --json                      # write main.json + loader
    python create.py --db                        # write main.db + loader
    python create.py --format json               # same as --json
    python create.py --format db                 # same as --db
    python create.py -l os subprocess --json     # add libs, output as JSON
    python create.py --json --json-path nodes.json
    python create.py --db --db-path nodes.db

Notes
-----
* main.py is truncated (opened "w") before every write — no stale lines.
* Global dedup by name — same class/function registered once.
* Modules walked shallow-first, so torch.nn.Conv2d wins over the
  internal torch.nn.modules.conv.Conv2d.
* torch is ALWAYS walked, whether or not it appears in --libraries.
* Budget model: each explicitly-requested library gets its own cap.
  --max-nodes sets the per-package cap.
* Top-level modules whose members live in a C extension (io -> _io,
  os -> posix, json -> _json, csv -> _csv, socket -> _socket, ...)
  are collected in full: the ownership check is skipped at depth 0.
* Deprecation warnings raised by walked modules are suppressed by
  redirecting stderr during the walk.
* Every BaseException subclass is moved into a single "Exceptions"
  category and carries a `qualname` so the codegen can emit valid
  Python for it.
* Enum-typed and object-typed parameter defaults are dropped, so the
  generated file always parses.  (`AwqBackend.AUTO` and friends.)
"""

import argparse
import contextlib
import datetime
import importlib
import inspect
import io
import json
import os
import pkgutil
import sqlite3
import sys
import warnings


# ============================================================== #
#  CONFIG                                                        #
# ============================================================== #

BASE_LIBRARIES = ["torch"]
BASE_CATEGORY = {"torch": "Torch"}

EXCEPTIONS_CATEGORY = "Exceptions"
EXCEPTIONS_COLOR    = "#A03A3A"

PER_PACKAGE_CAP  = 500
BASE_PACKAGE_CAP = 2000
EXTRA_ROOT_CAP   = 150

EXTRA_ROOTS = [
    ("Built-ins/io",       "io"),
    ("Built-ins/os",       "os"),
    ("Built-ins/os.path",  "os.path"),
    ("Built-ins/math",     "math"),
    ("Built-ins/random",   "random"),
    ("Built-ins/json",     "json"),
    ("Built-ins/pathlib",  "pathlib"),
    ("Built-ins/shutil",   "shutil"),
    ("Built-ins/tempfile", "tempfile"),
    ("Built-ins/time",     "time"),
    ("Built-ins/datetime", "datetime"),
    ("Built-ins/Exceptions", "builtins"),
]

_EXCEPTIONS_ONLY_ROOTS = {"builtins"}

SKIP_PREFIXES = (
    "torch._C",
    "torch._inductor",
    "torch._dynamo",
    "torch._functorch",
    "torch._native",
    "torch._vendor",
    "torch.onnx",
    "torch.jit",
    "torch.fx",
    "torch.testing",
    "torch.version",
    "torch.overrides",
    "torch.types",
    "torch.torch_version",
    "torch.utils.tensorboard",
)

MAX_DEPTH      = 4
MAX_INPUTS     = 15
OUT_FILE       = "main.py"
JSON_FILE      = "main.json"
DB_FILE        = "main.db"
PROGRESS_EVERY = 100

COLOR_PALETTE = [
    "#4A6B8A", "#8A4A4A", "#4A8A6B", "#6B4A8A",
    "#8A7A4A", "#4A7A8A", "#7A4A8A", "#7A6B3A",
]


# ============================================================== #
#  CLI                                                           #
# ============================================================== #

def _split_lib_token(tok):
    tok = str(tok).strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
        tok = tok[1:-1].strip()
    if tok.startswith("[") and tok.endswith("]"):
        tok = tok[1:-1]
    parts = tok.replace(" ", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _flatten_libraries(raw_lists):
    out = []
    for group in raw_lists:
        for tok in group:
            out.extend(_split_lib_token(tok))
    return out


def _build_parser():
    p = argparse.ArgumentParser(
        prog="create.py",
        description=(
            "Auto-generate the node library from installed Python "
            "packages.  torch is always walked.  Output can be a plain "
            "Python file (default), a JSON data file, or a SQLite "
            "database, in which case a small loader main.py is written."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  create.py\n"
            "  create.py -l os subprocess\n"
            "  create.py --json\n"
            "  create.py --db -l os\n"
            "  create.py --format json --json-path nodes.json\n"
        ),
    )
    p.add_argument(
        "-l", "--libraries", "--library", "--libs",
        dest="libraries",
        action="append", nargs="*", default=[],
        metavar="NAME",
        help="extra libraries to walk (in addition to torch).",
    )
    p.add_argument(
        "--format", "-f",
        dest="fmt",
        choices=("py", "json", "db"),
        default=None,
        help="output format.  py = embed specs in main.py (default).  "
             "json = write main.json + loader.  db = write main.db + "
             "loader.",
    )
    p.add_argument(
        "--json",
        dest="use_json",
        action="store_true",
        help="shortcut for --format json",
    )
    p.add_argument(
        "--db",
        dest="use_db",
        action="store_true",
        help="shortcut for --format db",
    )
    p.add_argument(
        "-o", "--output",
        dest="out_file",
        default=OUT_FILE,
        metavar="PATH",
        help="output main.py path (default: %(default)s)",
    )
    p.add_argument(
        "--json-path",
        dest="json_path",
        default=JSON_FILE,
        metavar="PATH",
        help="json data path when --json is used (default: %(default)s)",
    )
    p.add_argument(
        "--db-path",
        dest="db_path",
        default=DB_FILE,
        metavar="PATH",
        help="sqlite path when --db is used (default: %(default)s)",
    )
    p.add_argument(
        "--max-nodes",
        dest="max_nodes",
        type=int,
        default=BASE_PACKAGE_CAP,
        metavar="N",
        help="per-package cap on nodes (default: %(default)s)",
    )
    p.add_argument(
        "--max-depth",
        dest="max_depth",
        type=int,
        default=MAX_DEPTH,
        metavar="N",
        help="maximum submodule depth (default: %(default)s)",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="suppress progress output",
    )
    return p


def _resolve_format(args):
    """Precedence: --json / --db flags > --format > default 'py'."""
    if args.use_json and args.use_db:
        print("! --json and --db are mutually exclusive")
        sys.exit(2)
    if args.use_json:
        return "json"
    if args.use_db:
        return "db"
    if args.fmt:
        return args.fmt
    return "py"


# ============================================================== #
#  Package list                                                  #
# ============================================================== #

def build_packages(extra_libs):
    seen = set()
    ordered = []
    for name in BASE_LIBRARIES:
        if name not in seen:
            seen.add(name); ordered.append(name)
    for name in extra_libs:
        if not name or name in seen:
            continue
        seen.add(name); ordered.append(name)
    out = []
    for name in ordered:
        cat = BASE_CATEGORY.get(name) or name.split(".")[0]
        out.append((cat, name))
    return out


# ============================================================== #
#  Helpers                                                       #
# ============================================================== #

def py_str(s):
    if s is None:
        return '""'
    if not isinstance(s, str):
        s = str(s)
    if ("\n" in s and "\\" not in s
            and '"""' not in s and not s.endswith('"')):
        return '"""' + s + '"""'
    return repr(s)


def color_for(cat):
    if cat == EXCEPTIONS_CATEGORY:
        return EXCEPTIONS_COLOR
    return COLOR_PALETTE[hash(cat) % len(COLOR_PALETTE)]


def get_doc(obj):
    doc = None
    try:
        doc = obj.__doc__
    except Exception:
        pass
    if not doc and inspect.isclass(obj):
        try:
            doc = obj.__init__.__doc__
        except Exception:
            pass
    if doc is None:
        return ""
    if not isinstance(doc, str):
        try:
            doc = str(doc)
        except Exception:
            return ""
    try:
        doc = inspect.cleandoc(doc)
    except Exception:
        pass
    return doc.strip()


def infer_type(annotation):
    if annotation is None or annotation is inspect.Parameter.empty:
        return "any"
    name = getattr(annotation, "__name__", None) or str(annotation)
    low = name.lower()
    if low == "int":                       return "int"
    if low == "float":                     return "float"
    if low == "bool":                      return "bool"
    if low in ("str", "string"):           return "string"
    if "tensor" in low:                    return "vector"
    if "tuple" in low or "list" in low:    return "vector"
    if "dtype" in low or "device" in low:  return "string"
    return "any"


def get_params(obj):
    try:
        if inspect.isclass(obj):
            sig = inspect.signature(obj.__init__)
            params = list(sig.parameters.values())[1:]
        else:
            sig = inspect.signature(obj)
            params = list(sig.parameters.values())
    except (ValueError, TypeError):
        return []

    out = []
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name in ("self", "cls"):
            continue
        t = infer_type(p.annotation)
        if p.default is inspect.Parameter.empty:
            desc, dv = "", None
        else:
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
                if (not r or r.startswith("<")
                        or r.endswith(">")
                        or " object at 0x" in r):
                    dv = None
                elif isinstance(p.default, str):
                    dv = p.default
                else:
                    dv = r
        out.append((p.name, t, desc, dv))
        if len(out) >= MAX_INPUTS:
            break
    return out


def _is_exception_class(obj):
    try:
        return (inspect.isclass(obj)
                and issubclass(obj, BaseException))
    except TypeError:
        return False


def _exception_qualname(obj, fallback_name):
    try:
        module = getattr(obj, "__module__", "") or ""
    except Exception:
        module = ""
    name = None
    try:
        name = getattr(obj, "__qualname__", None)
    except Exception:
        name = None
    if not name:
        name = getattr(obj, "__name__", None) or fallback_name
    name = name.replace(".<locals>.", ".")
    if not module or module == "builtins":
        return name
    return module + "." + name


# ============================================================== #
#  Discovery                                                     #
# ============================================================== #

def _skip_module(name):
    return any(name == p or name.startswith(p + ".") for p in SKIP_PREFIXES)


def module_to_category(root_cat, dotted_name):
    parts = dotted_name.split(".")
    return "/".join([root_cat] + parts[1:])


def _safe_import(name):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return importlib.import_module(name)
    except BaseException:
        return None


def discover_modules(root_cat, package_name, max_depth, quiet=False):
    results = [(root_cat, package_name, 0)]
    pkg = _safe_import(package_name)
    if pkg is None:
        if not quiet:
            print("  ! could not import %s" % package_name)
        return results
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return results
    base_depth = package_name.count(".")
    err_buf = io.StringIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stderr(err_buf):
                for info in pkgutil.walk_packages(
                        pkg_path, package_name + "."):
                    name = info.name
                    leaf = name.rsplit(".", 1)[-1]
                    if leaf.startswith("_"):
                        continue
                    if _skip_module(name):
                        continue
                    depth = name.count(".") - base_depth
                    if depth > max_depth:
                        continue
                    results.append((module_to_category(root_cat, name),
                                    name, depth))
    except BaseException as ex:
        if not quiet:
            print("  ! walk failed for %s: %s" % (package_name, ex))
    results.sort(key=lambda r: (r[2], r[1]))
    return results


# ============================================================== #
#  Collect                                                       #
# ============================================================== #

def collect_from_module(cat, mod_path, seen_names, specs_out, limit):
    if len(specs_out) >= limit:
        return 0
    mod = _safe_import(mod_path)
    if mod is None:
        return 0
    top_level = "." not in mod_path
    root = mod_path.split(".")[0]
    real_root = getattr(mod, "__name__", root).split(".")[0]
    roots = {root, real_root}
    exc_only = mod_path in _EXCEPTIONS_ONLY_ROOTS
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
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        if not top_level:
            obj_mod = getattr(obj, "__module__", "") or ""
            if not any(obj_mod.startswith(r) for r in roots):
                continue
        is_exc = _is_exception_class(obj)
        if exc_only and not is_exc:
            continue
        seen_names.add(name)
        if is_exc:
            spec_cat = EXCEPTIONS_CATEGORY
            qualname = _exception_qualname(obj, name)
        else:
            spec_cat = cat
            qualname = None
        specs_out.append({
            "name":        name,
            "color":       color_for(spec_cat),
            "category":    spec_cat,
            "description": get_doc(obj),
            "qualname":    qualname,
            "inputs":      get_params(obj),
            "outputs":     [(name, "object",
                             "Result of %s.%s" % (mod_path, name))],
            "full_path":   "%s.%s" % (mod_path, name),
        })
        added += 1
    return added


def _walk_one_package(cat, pkg, seen_names, max_depth, cap, quiet=False):
    def say(*a):
        if not quiet:
            print(*a)
    pkg_specs = []
    modules = discover_modules(cat, pkg, max_depth, quiet)
    say("  %-16s -> %-10s (%d modules)" % (pkg, cat, len(modules)))
    for i, (mcat, mod_path, _d) in enumerate(modules, 1):
        if not quiet and i % PROGRESS_EVERY == 0:
            say("    ... %d / %d modules, %d nodes"
                % (i, len(modules), len(pkg_specs)))
        collect_from_module(mcat, mod_path, seen_names, pkg_specs, cap)
        if len(pkg_specs) >= cap:
            say("    cap reached for %s (%d nodes)" % (pkg, cap))
            break
    return pkg_specs


def collect(packages, max_depth, max_nodes, quiet=False):
    def say(*a):
        if not quiet:
            print(*a)
    all_specs = []
    seen_names = set()
    say("discovering modules ...")
    for cat, pkg in packages:
        pkg_specs = _walk_one_package(
            cat, pkg, seen_names, max_depth, max_nodes, quiet)
        all_specs.extend(pkg_specs)
        say("    -> %s: %d nodes" % (pkg, len(pkg_specs)))
    for cat, mod_path in EXTRA_ROOTS:
        pkg_specs = _walk_one_package(
            cat, mod_path, seen_names, max_depth, EXTRA_ROOT_CAP, quiet)
        all_specs.extend(pkg_specs)
    all_specs.sort(key=lambda s: (s["category"], s["name"].lower()))
    return all_specs


# ============================================================== #
#  emit — Python (embed SPECS)                                   #
# ============================================================== #

HEADER_EMBED = '''\
# Auto-generated by create.py — do not edit by hand.
#
# Source:  torch {version} ({torch_path})
# Output:  {out_file}
# Date:    {date}
# Nodes:   {node_count}
#
# Roots walked:
{libraries}
# Use the editor's Ctrl+G to write generated.py from the current graph,
# then F5 (or the Run toolbar button) to execute it.

import os
try:
    from helpers.Nodes.Nodes import (API, section, in_, out,
                                     PATH_TYPE,
                                     PATH_IN_NAME, PATH_OUT_NAME)
except ImportError:
    from Nodes import (API, section, in_, out,
                       PATH_TYPE,
                       PATH_IN_NAME, PATH_OUT_NAME)


def _print_env():
    import sys
    print("Python  %s" % sys.version.split()[0])
    try:
        import matplotlib
        print("matplotlib %s" % matplotlib.__version__)
    except Exception as ex:
        print("matplotlib NOT available (%s)" % ex)
    try:
        import PyQt5
        from PyQt5.QtCore import QT_VERSION_STR
        print("Qt      %s" % QT_VERSION_STR)
    except Exception:
        pass

_print_env()


api = API.instance()
api.clear()
api.register.node.clear()

try:
    try:
        from helpers.Nodes.Nodes import _register_builtins, _register_roles
    except ImportError:
        from Nodes import _register_builtins, _register_roles
    _register_builtins(api)
    _register_roles(api)
except Exception as _e:
    print("[builtins] restore failed:", _e)


SPECS = [
'''

# Loader header, used for --json and --db
HEADER_LOADER = '''\
# Auto-generated loader by create.py — do not edit by hand.
#
# Data file:  {data_file}
# Format:     {data_format}
# Source:     torch {version} ({torch_path})
# Date:       {date}
# Nodes:      {node_count}
#
# The specs live in {data_file}, not in this file.  Regenerate the
# data with `python create.py --{data_format}`.  This loader reads
# whichever data file is present (json or db) and registers each spec.

import json
import os
import sqlite3

try:
    from helpers.Nodes.Nodes import (API, section, in_, out,
                                     PATH_TYPE,
                                     PATH_IN_NAME, PATH_OUT_NAME)
except ImportError:
    from Nodes import (API, section, in_, out,
                       PATH_TYPE,
                       PATH_IN_NAME, PATH_OUT_NAME)


def _print_env():
    import sys
    print("Python  %s" % sys.version.split()[0])
    try:
        import matplotlib
        print("matplotlib %s" % matplotlib.__version__)
    except Exception as ex:
        print("matplotlib NOT available (%s)" % ex)
    try:
        import PyQt5
        from PyQt5.QtCore import QT_VERSION_STR
        print("Qt      %s" % QT_VERSION_STR)
    except Exception:
        pass

_print_env()


def _load_specs(json_path, db_path):
    """Read specs from whichever data file exists.  JSON wins."""
    if os.path.isfile(json_path):
        print("[loader] reading %s" % json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f).get("nodes", [])
    if os.path.isfile(db_path):
        print("[loader] reading %s" % db_path)
        con = sqlite3.connect(db_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT name, color, category, description, "
                "qualname, inputs, outputs, full_path FROM nodes")
            out = []
            for row in cur.fetchall():
                out.append({
                    "name":        row[0],
                    "color":       row[1],
                    "category":    row[2],
                    "description": row[3],
                    "qualname":    row[4],
                    "inputs":      json.loads(row[5]) if row[5] else [],
                    "outputs":     json.loads(row[6]) if row[6] else [],
                    "full_path":   row[7],
                })
            return out
        finally:
            con.close()
    print("[loader] no data file found; starting with an empty library")
    return []


api = API.instance()
api.clear()
api.register.node.clear()

try:
    try:
        from helpers.Nodes.Nodes import _register_builtins, _register_roles
    except ImportError:
        from Nodes import _register_builtins, _register_roles
    _register_builtins(api)
    _register_roles(api)
except Exception as _e:
    print("[builtins] restore failed:", _e)


SPECS = _load_specs({json_path!r}, {db_path!r})
for _s in SPECS:
    _s["on_exists"] = "keep"
n_ok, n_bad = api.register.node.bulk(SPECS)
print("Registered %d / %d templates" % (n_ok, n_ok + n_bad))
'''

FOOTER = '''\

# ============================================================== #
#  CUSTOM NODES                                                  #
# ============================================================== #

api.register_node(
    name        = "Download Model",
    color       = "#B07030",
    category    = "Utils",
    description = """\\
Downloads a model from HuggingFace or GitHub.

Inputs
------
username  HuggingFace user / org (or GitHub owner)
repo      Repository or model name
source    "hf" for HuggingFace, "github" for GitHub

Outputs
-------
Path      Local directory the model was saved to
Status    "ok", "cached" or an error message
""",
    inputs = [
        ("username", "string", "HuggingFace user / org", "someuser"),
        ("repo",     "string", "Repository or model name", "somemodel"),
        ("source",   "string", "hf | github", "hf"),
    ],
    outputs = [
        ("Path",   "string", "Local model directory"),
        ("Status", "string", "ok / cached / error text"),
    ],
)


# ============================================================== #
#  FLOW NODES                                                    #
# ============================================================== #

api.register_node(
    name="Start",
    color="#2E5C2E",
    category="Flow",
    description="Entry point of the pipeline.",
    flow=False,
    outputs=[("Next", PATH_TYPE, "First node in the chain")],
)

api.register_node(
    name="End",
    color="#5C2E2E",
    category="Flow",
    description="Exit point of the pipeline.",
    flow=False,
    inputs=[("Prev", PATH_TYPE, "Last node in the chain")],
)


# ============================================================== #
#  RUN                                                           #
# ============================================================== #

api.report.success("Registered %d templates" % len(api.templates()))
api.show()
api.app().exec_()
'''


def _format_libraries_line(packages):
    lines = []
    for cat, name in packages:
        lines.append("#   %-20s  ->  %s\n" % (name, cat))
    lines.append("#\n")
    lines.append("# Built-in roots:\n")
    for cat, name in EXTRA_ROOTS:
        lines.append("#   %-20s  ->  %s\n" % (name, cat))
    return "".join(lines)


def emit_python(specs, out_file, torch_version, torch_path, packages):
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(HEADER_EMBED.format(
            version=torch_version, torch_path=torch_path,
            out_file=out_file, date=date,
            node_count=len(specs),
            libraries=_format_libraries_line(packages),
        ))
        for spec in specs:
            f.write("    # %s\n" % spec["full_path"])
            f.write("    {\n")
            f.write('        "name":        %s,\n' % py_str(spec["name"]))
            f.write('        "color":       %s,\n' % py_str(spec["color"]))
            f.write('        "category":    %s,\n' % py_str(spec["category"]))
            f.write('        "description": %s,\n' % py_str(spec["description"]))
            if spec.get("qualname"):
                f.write('        "qualname":    %s,\n'
                        % py_str(spec["qualname"]))
            f.write('        "inputs": [\n')
            for (n, t, d, dv) in spec["inputs"]:
                if dv is not None:
                    f.write("            (%s, %s, %s, %s),\n"
                            % (py_str(n), py_str(t), py_str(d), py_str(dv)))
                else:
                    f.write("            (%s, %s, %s),\n"
                            % (py_str(n), py_str(t), py_str(d)))
            f.write("        ],\n")
            f.write('        "outputs": [\n')
            for (n, t, d) in spec["outputs"]:
                f.write("            (%s, %s, %s),\n"
                        % (py_str(n), py_str(t), py_str(d)))
            f.write("        ],\n")
            f.write("    },\n\n")
        f.write("]\n\n")
        f.write("for _s in SPECS:\n")
        f.write("    _s[\"on_exists\"] = \"keep\"\n")
        f.write("n_ok, n_bad = api.register.node.bulk(SPECS)\n")
        f.write("print(\"Registered %d / %d templates\" "
                "% (n_ok, n_ok + n_bad))\n")
        f.write(FOOTER)


# ============================================================== #
#  emit — JSON + loader                                          #
# ============================================================== #

def _spec_to_json(spec):
    """Tuples are not JSON; convert them to lists."""
    return {
        "name":        spec["name"],
        "color":       spec["color"],
        "category":    spec["category"],
        "description": spec["description"],
        "qualname":    spec.get("qualname"),
        "inputs":      [list(t) for t in spec["inputs"]],
        "outputs":     [list(t) for t in spec["outputs"]],
        "full_path":   spec["full_path"],
    }


def emit_json(specs, out_file, json_path,
              torch_version, torch_path, packages):
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "format":        "pytorchui-nodes",
        "version":       1,
        "torch_version": torch_version,
        "torch_path":    torch_path,
        "generated":     date,
        "node_count":    len(specs),
        "libraries":     [name for _cat, name in packages],
        "builtin_roots": [name for _cat, name in EXTRA_ROOTS],
        "nodes":         [_spec_to_json(s) for s in specs],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    header = (HEADER_LOADER
              .replace("{json_path!r}", repr(json_path))
              .replace("{db_path!r}", repr(DB_FILE))
              .replace("{data_file}", json_path)
              .replace("{data_format}", "json")
              .replace("{version}", torch_version)
              .replace("{torch_path}", torch_path)
              .replace("{date}", date)
              .replace("{node_count}", str(len(specs))))
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(FOOTER)


# ============================================================== #
#  emit — SQLite + loader                                        #
# ============================================================== #

def emit_db(specs, out_file, db_path,
            torch_version, torch_path, packages):
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if os.path.isfile(db_path):
        os.remove(db_path)

    con = sqlite3.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        for k, v in (
            ("format", "pytorchui-nodes"),
            ("version", "1"),
            ("torch_version", torch_version),
            ("torch_path", torch_path),
            ("generated", date),
            ("node_count", str(len(specs))),
        ):
            con.execute("INSERT INTO metadata VALUES (?, ?)", (k, v))

        con.execute("""
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT,
                category TEXT,
                description TEXT,
                qualname TEXT,
                inputs TEXT,
                outputs TEXT,
                full_path TEXT,
                UNIQUE(name)
            )
        """)
        con.execute("CREATE INDEX idx_nodes_category ON nodes(category)")
        con.execute("CREATE INDEX idx_nodes_full_path ON nodes(full_path)")

        for s in specs:
            con.execute(
                "INSERT OR IGNORE INTO nodes "
                "(name, color, category, description, qualname, "
                " inputs, outputs, full_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s["name"], s["color"], s["category"],
                    s["description"], s.get("qualname"),
                    json.dumps([list(t) for t in s["inputs"]]),
                    json.dumps([list(t) for t in s["outputs"]]),
                    s["full_path"],
                ),
            )
        con.commit()
    finally:
        con.close()

    with open(out_file, "w", encoding="utf-8") as f:
        _hdr = (HEADER_LOADER
                .replace("{json_path!r}", repr(JSON_FILE))
                .replace("{db_path!r}", repr(db_path))
                .replace("{data_file}", db_path)
                .replace("{data_format}", "db")
                .replace("{version}", torch_version)
                .replace("{torch_path}", torch_path)
                .replace("{date}", date)
                .replace("{node_count}", str(len(specs))))
        f.write(_hdr)
        f.write(FOOTER)


# ============================================================== #
#  Main                                                          #
# ============================================================== #

def main(argv=None):
    warnings.filterwarnings("ignore")
    parser = _build_parser()
    args = parser.parse_args(argv)

    fmt = _resolve_format(args)

    extra_libs = _flatten_libraries(args.libraries)
    packages = build_packages(extra_libs)

    if not args.quiet:
        print("output format:", fmt)
        print("roots to walk (torch is always first):")
        for cat, name in packages:
            print("  %-20s  ->  %s" % (name, cat))
        print()

    try:
        import torch
    except ImportError:
        print("torch is not installed for this interpreter.")
        sys.exit(1)

    version = getattr(torch, "__version__", "unknown")
    path    = getattr(torch, "__file__", "?")
    if not args.quiet:
        print("torch %s at %s" % (version, path))

    specs = collect(packages, args.max_depth, args.max_nodes, args.quiet)
    if not args.quiet:
        print("Collected %d nodes total" % len(specs))
        from collections import Counter
        c = Counter(s["category"] for s in specs)
        for cat, n in sorted(c.items()):
            print("  %-30s %d nodes" % (cat, n))

    # Remove the old output(s) so a crash mid-write can't leave stale
    # content behind.
    for p in (args.out_file, args.json_path, args.db_path):
        if os.path.isfile(p):
            try:
                os.remove(p)
                if not args.quiet:
                    print("Removed old %s" % p)
            except OSError as ex:
                print("  ! could not remove %s: %s" % (p, ex))

    if fmt == "py":
        emit_python(specs, args.out_file, version, path, packages)
        with open(args.out_file, "r", encoding="utf-8") as f:
            n = sum(1 for _ in f)
        if not args.quiet:
            print("Wrote %s (%d lines)" % (args.out_file, n))
    elif fmt == "json":
        emit_json(specs, args.out_file, args.json_path,
                  version, path, packages)
        if not args.quiet:
            print("Wrote %s (data)" % args.json_path)
            print("Wrote %s (loader)" % args.out_file)
    elif fmt == "db":
        emit_db(specs, args.out_file, args.db_path,
                version, path, packages)
        if not args.quiet:
            print("Wrote %s (data)" % args.db_path)
            print("Wrote %s (loader)" % args.out_file)

    if not args.quiet:
        print()
        print("Next:")
        print("  python main.py")


if __name__ == "__main__":
    main()