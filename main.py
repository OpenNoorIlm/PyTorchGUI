# Auto-generated loader by create.py — do not edit by hand.
#
# Data file:  main.db
# Format:     db
# Source:     torch 2.14.0+cpu (/home/bismillah/.local/lib/python3.10/site-packages/torch/__init__.py)
# Date:       2026-09-18 19:07:22
# Nodes:      33515
#
# The specs live in main.db, not in this file.  Regenerate the
# data with `python create.py --db`.  This loader reads
# whichever data file is present (json or db).

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
    if os.path.isfile(json_path):
        print("[loader] reading %s" % json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f).get("nodes", [])
    if os.path.isfile(db_path):
        print("[loader] reading %s" % db_path)
        con = sqlite3.connect(db_path)
        try:
            cur = con.cursor()
            cur.execute("PRAGMA table_info(nodes)")
            cols = [r[1] for r in cur.fetchall()]
            has_nc = "node_class" in cols
            if has_nc:
                sel = ("SELECT name, color, category, description, "
                       "qualname, inputs, outputs, full_path, node_class "
                       "FROM nodes")
            else:
                sel = ("SELECT name, color, category, description, "
                       "qualname, inputs, outputs, full_path "
                       "FROM nodes")
            cur.execute(sel)
            out = []
            for row in cur.fetchall():
                spec = {
                    "name":        row[0],
                    "color":       row[1],
                    "category":    row[2],
                    "description": row[3],
                    "qualname":    row[4],
                    "inputs":      json.loads(row[5]) if row[5] else [],
                    "outputs":     json.loads(row[6]) if row[6] else [],
                    "full_path":   row[7],
                }
                if has_nc and row[8]:
                    spec["node_class"] = row[8]
                out.append(spec)
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


SPECS = _load_specs('main.json', 'main.db')
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
    description = """\
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
