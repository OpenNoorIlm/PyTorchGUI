#!/usr/bin/env python3
"""
add_call_class.py — add Call Class, fix dotted-name calls, add kwargs
                    to Method Call.

Three independent changes:

1.  New nodes under "Built-ins/Classes":
      Call Class        → NAME(*args), dotted or bare
      Class Attribute   → getattr(ClassName, "CONST")

2.  call_by_name codegen now handles dotted names.  Previously the
    whole Name was wrapped in globals()[str(...)], so:
        Name="Point"      -> globals()['Point'](...)          ok
        Name="math.sqrt"  -> globals()['math.sqrt'](...)      KeyError
    Now dotted names emit directly:
        Name="math.sqrt"  -> math.sqrt(...)
    and bare names keep the globals() lookup.

3.  Method Call gains a Kwargs field, and the codegen forwards it:
        Object="p", Method="dist", Args="[1]", Kwargs="{'key': 2}"
        -> p.dist(*([1]), **({'key': 2}))

Idempotent.  Backs up Nodes.py to Nodes.py.bak_callclass.
"""

import os
import shutil
import py_compile
import sys


def _find_nodes():
    for p in ("helpers/Nodes/Nodes.py", "Nodes.py"):
        if os.path.isfile(p):
            return p
    return None


# --------------------------------------------------------------------- #
#  Anchors — raw triple-quoted so backslashes stay literal              #
# --------------------------------------------------------------------- #

A_CLASS = r'''    ("Built-ins/Classes", "Define Class", "class_",
     "**class NAME(bases):** body via blocks.",
     [("Name", "string", "Name", "'MyClass'"),
      ("Bases", "string", "Bases", "''")], [], None, None),
'''

A_CLASS_NEW = A_CLASS + r'''    ("Built-ins/Classes", "Call Class", "call_by_name",
     "**Instantiate a class.**  NAME(*args).\n\n"
     "- `NAME` may be a bare class name (`Point`) or a dotted\n"
     "  path (`math.Vector`, `subprocess.Popen`).\n"
     "- `Args` is a Python list of positional arguments:\n"
     "  `[3, 4]`, `[cmd, shell=True]`, or `[]` for none.\n"
     "- The output is the new instance; feed it into\n"
     "  **Method Call** or **Get Attr**.",
     [("Name", "string", "Class name or dotted path", "'Point'"),
      ("Args", "any", "Positional arguments as a list", "[]")],
     [("Instance", "any", "The newly created object")],
     None, None),
    ("Built-ins/Classes", "Class Attribute", "attr_get",
     "**Read a class-level attribute.**\n\n"
     "`getattr(ClassName, \"CONST\")` — class constants, class\n"
     "variables, classmethods, or staticmethods.  Feed the\n"
     "class (not an instance) into `Object`.",
     [("Object", "any", "A class object", "None"),
      ("Attr", "string", "Attribute name", "'CONST'")],
     [("Result", "any", "Attribute value")],
     None, None),
'''


A_CALL_BY_NAME = r'''            if kind == "call_by_name":
                L.append("%s%s = globals()[str(%s)](*(%s))"
                         % (pad, var, B.get("Name") or "'f'", B.get("Args") or "[]"))
                return L, miss
'''

A_CALL_BY_NAME_NEW = r'''            if kind == "call_by_name":
                name_lit = B.get("Name") or "'f'"
                args_lit = B.get("Args") or "[]"
                raw = str(name_lit).strip()
                # Determine if the user typed a name (quoted in the
                # generated code) or wired an expression.
                if (len(raw) >= 2
                        and raw[0] == raw[-1]
                        and raw[0] in ("'", '"')):
                    bare = raw[1:-1]
                    quoted = True
                else:
                    bare = raw
                    quoted = False
                if quoted:
                    # Dotted path like math.sqrt: emit directly.
                    if ("." in bare
                            and _re.match(
                                r"^[A-Za-z_][A-Za-z0-9_]*"
                                r"(\.[A-Za-z_][A-Za-z0-9_]*)*$",
                                bare)):
                        L.append("%s%s = %s(*(%s))"
                                 % (pad, var, bare, args_lit))
                    else:
                        L.append("%s%s = globals()[str(%s)](*(%s))"
                                 % (pad, var, name_lit, args_lit))
                else:
                    # Wired expression: call it directly.
                    L.append("%s%s = (%s)(*(%s))"
                             % (pad, var, bare, args_lit))
                return L, miss
'''


A_METHOD_ENTRY = r'''    ("Built-ins/Objects", "Method Call", "method_call",
     "**obj.method(*args).**",
     [("Object", "any", "Object", "None"),
      ("Method", "string", "Method", "'append'"),
      ("Args", "any", "Args", "[]")],
     [("Result", "any", "Return")], None, None),
'''

A_METHOD_ENTRY_NEW = r'''    ("Built-ins/Objects", "Method Call", "method_call",
     "**obj.method(*args, **kwargs).**\n\n"
     "- `Object` is any expression evaluating to an instance\n"
     "  (a **Call Class** output, a **Get Variable**, ...).\n"
     "- `Method` is the method name, without parentheses.\n"
     "- `Args` is a Python list of positional arguments.\n"
     "- `Kwargs` is a Python dict of keyword arguments.  Leave it\n"
     "  empty (`{}`) if the method takes none.",
     [("Object", "any", "Object", "None"),
      ("Method", "string", "Method name", "'append'"),
      ("Args", "any", "Positional args as a list", "[]"),
      ("Kwargs", "any", "Keyword args as a dict", "{}")],
     [("Result", "any", "Return value")], None, None),
'''


A_METHOD_CODEGEN = r'''            if kind == "method_call":
                obj = B.get("Object") or "None"
                meth = str(B.get("Method") or "'m'").strip("'\"")
                L.append("%s%s = %s.%s(*(%s))"
                         % (pad, var, obj, meth, B.get("Args") or "[]"))
                return L, miss
'''

A_METHOD_CODEGEN_NEW = r'''            if kind == "method_call":
                obj = B.get("Object") or "None"
                meth = str(B.get("Method") or "'m'").strip("'\"")
                args_lit = B.get("Args") or "[]"
                kwargs_lit = B.get("Kwargs")
                if kwargs_lit and kwargs_lit.strip() not in ("{}", ""):
                    L.append("%s%s = %s.%s(*(%s), **(%s))"
                             % (pad, var, obj, meth, args_lit,
                                kwargs_lit))
                else:
                    L.append("%s%s = %s.%s(*(%s))"
                             % (pad, var, obj, meth, args_lit))
                return L, miss
'''


A_GETATTR_ENTRY = r'''    ("Built-ins/Objects", "Get Attr", "attr_get",
     "**getattr(obj, attr).**",
     [("Object", "any", "Object", "None"),
      ("Attr", "string", "Attr", "'x'")],
     [("Result", "any", "Value")], None, None),
'''

A_GETATTR_ENTRY_NEW = r'''    ("Built-ins/Objects", "Get Attr", "attr_get",
     "**getattr(obj, attr).**\n\n"
     "Reads an attribute from any object:\n\n"
     "- instance variables: feed the instance into `Object`\n"
     "- class constants: feed the class into `Object`\n"
     "- for nested access (obj.a.b), use two Get Attr nodes",
     [("Object", "any", "Instance or class", "None"),
      ("Attr", "string", "Attribute name", "'x'")],
     [("Result", "any", "Value")], None, None),
'''


PATCHES = [
    ("Call Class + Class Attribute nodes",
     A_CLASS, A_CLASS_NEW),
    ("call_by_name handles dotted names",
     A_CALL_BY_NAME, A_CALL_BY_NAME_NEW),
    ("Method Call gains a Kwargs field",
     A_METHOD_ENTRY, A_METHOD_ENTRY_NEW),
    ("method_call forwards kwargs",
     A_METHOD_CODEGEN, A_METHOD_CODEGEN_NEW),
    ("Get Attr description covers classes",
     A_GETATTR_ENTRY, A_GETATTR_ENTRY_NEW),
]


def main():
    path = _find_nodes()
    if not path:
        print("Could not find helpers/Nodes/Nodes.py or Nodes.py")
        sys.exit(1)

    print("Target:", path)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    applied = 0
    already = 0
    missed = []

    for label, old, new in PATCHES:
        if new in src:
            print("  [ok] %s" % label)
            already += 1
            continue
        if old not in src:
            print("  [!!] %s (anchor not found)" % label)
            missed.append(label)
            continue
        src = src.replace(old, new, 1)
        applied += 1
        print("  [+] %s" % label)

    if applied == 0:
        print()
        if already:
            print("Everything is already patched.")
        else:
            print("No patches could be applied.  Nothing was written.")
            for m in missed:
                print("   -", m)
        return

    backup = path + ".bak_callclass"
    shutil.copy(path, backup)
    print()
    print("Backup ->", backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    try:
        py_compile.compile(path, doraise=True)
        print("Syntax OK.  %d patch(es) applied." % applied)
    except py_compile.PyCompileError as e:
        shutil.copy(backup, path)
        print("! syntax error — restored from backup")
        print(e)
        sys.exit(1)

    if missed:
        print()
        print("Skipped:")
        for m in missed:
            print("   -", m)

    print()
    print("New nodes (library sidebar):")
    print("  Built-ins/Classes → Call Class")
    print("  Built-ins/Classes → Class Attribute")
    print()
    print("Updated nodes:")
    print("  Built-ins/Objects → Method Call  (added Kwargs field)")
    print("  Call Function / Call Class       (dotted names work)")
    print()
    print("Typical class workflow:")
    print("  1. Define Class     -> class object")
    print("  2. Call Class       -> instance")
    print("  3. Method Call      -> call a method on the instance")
    print("  4. Get Attr         -> read an attribute")


if __name__ == "__main__":
    main()