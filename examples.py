#!/usr/bin/env python3
"""
make_examples_extra.py — build example graphs using literal value nodes

Run:
    cd ~/Downloads/PyTorchUI
    python3 make_examples_extra.py
    rm -f generated.py
    python3 main.py
"""

import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def N(api, name, x=0, y=0, id=None, **inputs):
    """Add a node and set its literal input values."""
    n = api.add_node(name, x=x, y=y, id=id)
    for k, v in inputs.items():
        s = n.socket(k, is_input=True)
        if s is not None:
            s.value = v
    return n


def attach(api, parent_id, *child_ids):
    for c in child_ids:
        try:
            api.blocks.attach(parent_id, c)
        except Exception as ex:
            print("  ! attach %s -> %s: %s" % (parent_id, c, ex))


# --------------------------------------------------------------------------- #
#  Builders                                                                   #
# --------------------------------------------------------------------------- #

def ex_values(api):
    """08_values.json — literals + print."""
    s = N(api, "String Literal", x=-500, y=-200, id="s", Value="'hello world'")
    i = N(api, "Int Literal",    x=-500, y=  20, id="i", Value="42")
    f = N(api, "Float Literal",  x=-500, y= 200, id="f", Value="3.14")
    b = N(api, "Bool Literal",   x=-500, y= 380, id="b", Value="True")
    lst = N(api, "List Literal", x=-150, y=-200, id="l",
            Item1="1", Item2="2", Item3="3")
    d = N(api, "Dict Literal", x=-150, y=100, id="d",
          K1="'a'", V1="1", K2="'b'", V2="2")
    p1 = N(api, "print", x=250, y=-200, id="p1", Value=None)
    p2 = N(api, "print", x=250, y=  20, id="p2", Value=None)
    p3 = N(api, "print", x=250, y= 200, id="p3", Value=None)
    p4 = N(api, "print", x=250, y= 380, id="p4", Value=None)
    p5 = N(api, "print", x=250, y=-100, id="p5", Value=None)
    p6 = N(api, "print", x=250, y= 150, id="p6", Value=None)
    api.connect("s", "Result", "p1", "Value")
    api.connect("i", "Result", "p2", "Value")
    api.connect("f", "Result", "p3", "Value")
    api.connect("b", "Result", "p4", "Value")
    api.connect("l", "Result", "p5", "Value")
    api.connect("d", "Result", "p6", "Value")
    api.chain_path("s", "i", "f", "b", "l", "d", "p1", "p2", "p3", "p4", "p5", "p6")


def ex_hello(api):
    """09_hello.json — a single print statement."""
    s = N(api, "String Literal", x=-200, y=0, id="s", Value="'Hello, world!'")
    p = N(api, "print", x=150, y=0, id="p", Value=None)
    api.connect("s", "Result", "p", "Value")
    api.chain_path("s", "p")


def ex_variables(api):
    """10_variables.json — set and get."""
    s = N(api, "Set Variable", x=-200, y=-100, id="set1",
          Name="total", Value=None)
    lit = N(api, "Int Literal", x=-500, y=-100, id="lit", Value="42")
    g = N(api, "Get Variable", x=150, y=-100, id="get1", Name="total")
    p = N(api, "print", x=450, y=-100, id="p", Value=None)
    api.connect("lit", "Result", "set1", "Value")
    api.connect("get1", "Value", "p", "Value")
    api.chain_path("lit", "set1", "get1", "p")


def ex_function(api):
    """11_function.json — define square + call."""
    df = N(api, "Define Function", x=-400, y=-200, id="df",
           Name="square", Args="n")
    binop = N(api, "Binary Op", x=-400, y=100, id="op",
              A="n", Op="'*'", B="n")
    ret = N(api, "Return", x=-100, y=100, id="ret", Value=None)
    api.connect("op", "Result", "ret", "Value")
    attach(api, "df", "op", "ret")

    call = N(api, "Call Function", x=200, y=-200, id="call",
             Name="square", Args="[7]")
    p = N(api, "print", x=500, y=-200, id="p", Value=None)
    api.connect("call", "Result", "p", "Value")
    api.chain_path("df", "call", "p")


def ex_loop(api):
    """12_loop.json — for i in range(5): print(i)."""
    rng = N(api, "range", x=-500, y=-200, id="rng", Start="0", Stop="5")
    fr = N(api, "For", x=-200, y=-200, id="fr", Var="i", Iterable=None)
    p = N(api, "print", x=100, y=100, id="p", Value="i")
    api.connect("rng", "Result", "fr", "Iterable")
    attach(api, "fr", "p")
    api.chain_path("rng", "fr")


def ex_class(api):
    """13_class.json — Point with __init__ and dist."""
    cls = N(api, "Define Class", x=-700, y=-300, id="cls",
            Name="Point", Bases="")

    init = N(api, "Define Function", x=-700, y=-100, id="init",
             Name="__init__", Args="self, x, y")
    set_x = N(api, "Set Variable", x=-700, y=100, id="sx",
              Name="self.x", Value="x")
    set_y = N(api, "Set Variable", x=-700, y=280, id="sy",
              Name="self.y", Value="y")
    attach(api, "init", "sx", "sy")

    dist = N(api, "Define Function", x=-400, y=-100, id="dist",
             Name="dist", Args="self")
    bin1 = N(api, "Binary Op", x=-400, y=100, id="b1",
             A="self.x", Op="'*'", B="self.x")
    bin2 = N(api, "Binary Op", x=-400, y=280, id="b2",
             A="self.y", Op="'*'", B="self.y")
    add = N(api, "Binary Op", x=-400, y=460, id="add", A=None, Op="'+'", B=None)
    ret = N(api, "Return", x=-100, y=460, id="ret", Value=None)
    api.connect("b1", "Result", "add", "A")
    api.connect("b2", "Result", "add", "B")
    api.connect("add", "Result", "ret", "Value")
    attach(api, "dist", "b1", "b2", "add", "ret")

    attach(api, "cls", "init", "dist")

    new = N(api, "Call Function", x=200, y=-300, id="new",
            Name="Point", Args="[3, 4]")
    setvar = N(api, "Set Variable", x=500, y=-300, id="sv",
               Name="p", Value=None)
    api.connect("new", "Result", "sv", "Value")

    get = N(api, "Get Variable", x=500, y=-100, id="gv", Name="p")
    meth = N(api, "Method Call", x=800, y=-100, id="mc",
             Object=None, Method="dist", Args="[]")
    p = N(api, "print", x=1100, y=-100, id="p", Value=None)
    api.connect("gv", "Value", "mc", "Object")
    api.connect("mc", "Result", "p", "Value")
    api.chain_path("cls", "new", "sv", "gv", "mc", "p")


def ex_try(api):
    """14_try.json — try / except / finally."""
    tr = N(api, "Try", x=-500, y=-200, id="tr")
    raise_n = N(api, "Raise", x=-500, y=50, id="raise",
                Exception="ValueError('boom')")
    exc = N(api, "Except", x=-500, y=250, id="exc", Exception="ValueError")
    p1 = N(api, "print", x=-200, y=400, id="p1", Value="'caught'")
    fin = N(api, "Finally", x=-500, y=550, id="fin")
    p2 = N(api, "print", x=-200, y=700, id="p2", Value="'done'")
    attach(api, "tr", "raise", "exc", "fin")
    attach(api, "exc", "p1")
    attach(api, "fin", "p2")
    api.chain_path("tr")


def ex_dict_iter(api):
    """15_dict_iter.json — build a dict, print its keys."""
    d = N(api, "Dict Literal", x=-400, y=-100, id="d",
          K1="'a'", V1="1", K2="'b'", V2="2")
    keys = N(api, "dict.keys", x=-100, y=-100, id="keys", Value=None)
    p = N(api, "print", x=250, y=-100, id="p", Value=None)
    api.connect("d", "Result", "keys", "Value")
    api.connect("keys", "Result", "p", "Value")
    api.chain_path("d", "keys", "p")


def ex_comprehension(api):
    """16_comprehension.json — [x*x for x in range(5)]"""
    lc = N(api, "List Comp", x=-200, y=-100, id="lc",
           Expr="x*x", Var="x", Iterable="range(5)", Condition="")
    p = N(api, "print", x=250, y=-100, id="p", Value=None)
    api.connect("lc", "Result", "p", "Value")
    api.chain_path("lc", "p")


EXAMPLES = [
    ("08_values.json",        ex_values),
    ("09_hello.json",         ex_hello),
    ("10_variables.json",     ex_variables),
    ("11_function.json",      ex_function),
    ("12_loop.json",          ex_loop),
    ("13_class.json",         ex_class),
    ("14_try.json",           ex_try),
    ("15_dict_iter.json",     ex_dict_iter),
    ("16_comprehension.json", ex_comprehension),
]


def main():
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    from helpers.Nodes.Nodes import APICli
    cli = APICli.instance()
    cli.register.node.clear()   # also re-registers built-ins + roles + values

    os.makedirs("examples", exist_ok=True)

    for name, builder in EXAMPLES:
        cli.clear()
        try:
            builder(cli)
        except Exception as ex:
            print("  %-24s FAILED: %s" % (name, ex))
            continue
        path = os.path.join("examples", name)
        cli.save(path)
        print("  %-24s %2d nodes, %2d edges"
              % (name, len(cli.nodes()), len(cli.edges())))

    print()
    print("Done.  Open with File -> Open... in the editor.")


if __name__ == "__main__":
    main()