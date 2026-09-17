#!/usr/bin/env python3
"""
create.py — auto-generate main.py from the installed Python package tree

Run:
    cd ~/Downloads/PyTorchUI
    python create.py                        # torch only (default)
    python create.py -l os subprocess       # torch + os + subprocess
    python create.py -l '[json,math]'       # bracket-style list
    python create.py --libraries=os,re      # comma-separated
    python create.py -l os -l subprocess    # repeated flag
    python main.py                          # launches the editor

Then, inside the editor:
    Ctrl+G  or  toolbar "Generate"   -> writes generated.py from the graph
    F5      or  toolbar "Run"        -> runs generated.py

Notes
-----
* main.py is truncated (opened "w") before every write — no stale lines.
* Global dedup by name — same class/function registered once.
* Modules walked shallow-first, so torch.nn.Conv2d wins over the
  internal torch.nn.modules.conv.Conv2d.
* torch is ALWAYS walked, whether or not it appears in --libraries.
* Budget model: each explicitly-requested library gets its own cap,
  so a saturated torch tree cannot starve the extras you asked for.
  --max-nodes sets the per-package cap, not a global one.
* Top-level modules whose members live in a C extension (io -> _io,
  os -> posix, json -> _json, csv -> _csv, socket -> _socket, ...)
  are collected in full: the ownership check is skipped at depth 0.
* Deprecation warnings raised by walked modules are suppressed by
  redirecting stderr during the walk.

Exception handling
------------------
Every class that is a subclass of BaseException — from torch, from any
library passed with -l, and from the built-in Built-ins/* roots — is
moved into a single top-level "Exceptions" category.  Its emitted spec
also carries a `qualname` field, e.g.

    "qualname": "torch.OutOfMemoryError"

The editor's codegen uses that qualname so a placed exception node
produces valid Python:

    OutOfMemoryError_1 = torch.OutOfMemoryError()

with the right import (`import torch`) added automatically.  For
built-in exceptions (OSError, ValueError, ...) the qualname is just
the bare class name, so `ValueError_1 = ValueError()` is emitted with
no import.

Emitted main.py calls api.register.node.bulk(SPECS) so the library
rebuilds exactly once.
"""

import argparse
import contextlib
import datetime
import importlib
import inspect
import io
import os
import pkgutil
import sys
import warnings


# ============================================================== #
#  CONFIG                                                        #
# ============================================================== #

BASE_LIBRARIES = ["torch"]
BASE_CATEGORY = {"torch": "Torch"}

# Every BaseException subclass ends up under this one category.
EXCEPTIONS_CATEGORY = "Exceptions"
EXCEPTIONS_COLOR    = "#A03A3A"

# Budgets, in nodes.  Per-package, not global.
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
    # builtins contributes only its exception classes; the rest of
    # dir(builtins) is covered by the hand-curated roots above and
    # by the ROLES in Nodes.py.
    ("Built-ins/Exceptions", "builtins"),
]

# Roots whose members get filtered before being collected.  For
# builtins we only want exceptions — otherwise we'd flood the library
# with list, dict, int, print, len, ...
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
PROGRESS_EVERY = 100

COLOR_PALETTE = [
    "#4A6B8A", "#8A4A4A", "#4A8A6B", "#6B4A8A",
    "#8A7A4A", "#4A7A8A", "#7A4A8A", "#7A6B3A",
]


# ============================================================== #
#  CLI parsing (argparse)                                        #
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
            "Auto-generate main.py from the installed Python package "
            "tree.  torch is always walked first; use --libraries to "
            "walk additional packages (os, subprocess, json, re, ...)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  create.py\n"
            "  create.py -l os subprocess\n"
            "  create.py -l '[json,math]'\n"
            "  create.py --libraries=os,subprocess,re\n"
            "  create.py -l os -l subprocess -l json\n"
        ),
    )
    p.add_argument(
        "-l", "--libraries", "--library", "--libs",
        dest="libraries",
        action="append", nargs="*", default=[],
        metavar="NAME",
        help=("library (or list) to walk in addition to torch. "
              "Accepts space-separated, comma-separated, or bracketed "
              "'[os,subprocess]' form.  May be repeated."),
    )
    p.add_argument("-o", "--output", dest="out_file", default=OUT_FILE,
                   metavar="PATH", help="output file (default: %(default)s)")
    p.add_argument("--max-nodes", dest="max_nodes", type=int,
                   default=BASE_PACKAGE_CAP, metavar="N",
                   help=("per-package cap on nodes.  Torch uses this value; "
                         "each extra library uses the same value.  "
                         "(default: %(default)s)"))
    p.add_argument("--max-depth", dest="max_depth", type=int,
                   default=MAX_DEPTH, metavar="N",
                   help="maximum submodule depth to walk (default: %(default)s)")
    p.add_argument("--quiet", dest="quiet", action="store_true",
                   help="suppress progress output")
    return p


# ============================================================== #
#  Package list construction                                     #
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
#  Emit helpers                                                  #
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
            try:
                desc = "Default: %r" % (p.default,)
            except Exception:
                desc = "Has default"
            if isinstance(p.default, str) and len(p.default) < 60:
                dv = p.default
            elif (isinstance(p.default, (int, float, bool))
                    and p.default is not None):
                dv = repr(p.default)
            else:
                dv = None
        out.append((p.name, t, desc, dv))
        if len(out) >= MAX_INPUTS:
            break
    return out


# ============================================================== #
#  Exception detection                                           #
# ============================================================== #

def _is_exception_class(obj):
    try:
        return (inspect.isclass(obj)
                and issubclass(obj, BaseException))
    except TypeError:
        return False


def _exception_qualname(obj, fallback_name):
    """
    Return the Python expression the codegen should emit for `obj`.

    Examples
    --------
    ValueError                       -> "ValueError"          (builtin)
    os.error (alias of OSError)      -> "OSError"             (builtin)
    torch.OutOfMemoryError           -> "torch.OutOfMemoryError"
    subprocess.CalledProcessError    -> "subprocess.CalledProcessError"
    csv.Error                        -> "csv.Error"

    The rule:
      * if the exception's __module__ is "builtins" (or empty), use just
        its name — no import needed
      * otherwise prefix the name with its __module__ — the editor's
        codegen will turn that prefix into an `import <module>` statement
    """
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
    # strip <locals> if it ever leaks out of a factory function
    name = name.replace(".<locals>.", ".")
    if not module or module == "builtins":
        return name
    return module + "." + name


# ============================================================== #
#  Module discovery                                              #
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
    """
    Collect classes/functions from one module into specs_out, stopping
    when specs_out already holds `limit` entries.
    """
    if len(specs_out) >= limit:
        return 0

    mod = _safe_import(mod_path)
    if mod is None:
        return 0

    top_level = "." not in mod_path
    root = mod_path.split(".")[0]
    real_root = getattr(mod, "__name__", root).split(".")[0]
    roots = {root, real_root}

    # If this root only contributes exceptions, skip everything else.
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
            # Move to the shared Exceptions category and give it the
            # qualname the codegen needs to produce valid Python.
            spec_cat  = EXCEPTIONS_CATEGORY
            qualname  = _exception_qualname(obj, name)
        else:
            spec_cat  = cat
            qualname  = None

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

    for i, (mcat, mod_path, _depth) in enumerate(modules, 1):
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

    for i, (cat, pkg) in enumerate(packages):
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
#  Emit main.py                                                  #
# ============================================================== #

HEADER = '''\
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


# ============================================================== #
#  ENVIRONMENT DIAGNOSTICS                                       #
# ============================================================== #

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


# ============================================================== #
#  BOOT                                                          #
# ============================================================== #

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


# ============================================================== #
#  GENERATED NODES                                               #
# ============================================================== #

SPECS = [
'''

FOOTER = '''\
]

for _s in SPECS:
    _s["on_exists"] = "keep"
n_ok, n_bad = api.register.node.bulk(SPECS)
print("Registered %d / %d templates" % (n_ok, n_ok + n_bad))


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


def emit(specs, out_file, torch_version, torch_path, packages):
    date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(HEADER.format(
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
            # Emit qualname only for exception specs.  Non-exception
            # specs keep the old behaviour where the codegen infers the
            # import from the category (Torch/nn -> nn.Linear).
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
        f.write(FOOTER)


# ============================================================== #
#  Main                                                          #
# ============================================================== #

def main(argv=None):
    warnings.filterwarnings("ignore")

    parser = _build_parser()
    args = parser.parse_args(argv)

    extra_libs = _flatten_libraries(args.libraries)
    packages   = build_packages(extra_libs)

    if not args.quiet:
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

    if os.path.isfile(args.out_file):
        try:
            os.remove(args.out_file)
            if not args.quiet:
                print("Removed old %s" % args.out_file)
        except OSError as ex:
            print("  ! could not remove %s: %s" % (args.out_file, ex))

    emit(specs, args.out_file, version, path, packages)
    with open(args.out_file, "r", encoding="utf-8") as f:
        n = sum(1 for _ in f)

    if not args.quiet:
        print("Wrote %s (%d lines)" % (args.out_file, n))
        print()
        print("Next:")
        print("  python main.py")


if __name__ == "__main__":
    main()