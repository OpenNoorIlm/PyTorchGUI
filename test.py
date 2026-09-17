from helpers.Nodes.Nodes import API, section, in_, out

api = API.instance()
api.clear()
api.show()

# ============================================================== #
#  REGISTER CUSTOM NODES                                         #
# ============================================================== #

api.register_node(
    "Import Torch",
    color="#8A4A4A", category="AI",
    description="Imports torch and returns the module.",
    inputs=[("Device", "string", "cpu / cuda"),
            ("DType",  "string", "float32 / float16")],
    outputs=[("Module", "object", "The torch module")]
)

api.register_node(
    "Tensor",
    color="#4A6B8A", category="AI",
    description="Creates a tensor from a shape.",
    sections=[
        section("Inputs",
                in_("Shape", "vector", "Shape as a 3-vector"),
                in_("Fill",  "float",  "Fill value"),
                description="Everything that goes into the tensor"),
        section("Outputs",
                out("Tensor", "object", "The tensor object"),
                description="What comes out"),
    ],
)

# ============================================================== #
#  DYNAMIC NODE  —  add sockets at runtime from the sidebar      #
# ============================================================== #

api.register_node(
    "Device List",
    color="#4A6B8A", category="AI",
    description="A dynamic list of device inputs.\n"
                "Select it and use the [+], [++], [−] buttons on the\n"
                "sidebar to add or remove sockets live.",
    dynamic=True,
    inputs=[("Device", "string", "cpu / cuda")],
    outputs=[("Result", "object", "Combined result")],
)

api.report.success(f"Registered 3 nodes · {len(api.templates())} templates total")

# ============================================================== #
#  BUILD THE GRAPH                                               #
# ============================================================== #

api.add_node("Image Input",  x=-520, y=-240, id="img")
api.add_node("Prompt",       x=-520, y=  60, id="prm")
api.add_node("Import Torch", x=-520, y= 260, id="torch")
api.add_node("Sampler",      x=-120, y=-160, id="smp",
             metadata={"model": "sdxl", "steps": 30})
api.add_node("Viewer",       x= 580, y=  40, id="view")

api.report.info("Placed 5 nodes")

api.connect("prm", "Text",   "smp",  "Prompt")
api.connect("img", "Image",  "smp",  "Image")
api.connect("smp", "Result", "view", "Image")

api.report.success("Linked 3 connections")

# ============================================================== #
#  DYNAMIC NODE EXAMPLE                                          #
# ============================================================== #

dl = api.add_node("Device List", x=580, y=-200, id="dl")

# Programmatic growth: add 4 more inputs to section 0 (the "Inputs" section)
for _ in range(4):
    dl.add_socket(0, True)

# Add 2 extra outputs to the same section
for _ in range(2):
    dl.add_socket(0, False)

api.report.success(
    f"Device List now has {len(dl.inputs)} inputs · "
    f"{len(dl.outputs)} outputs — click it to see the [+][++][−] buttons"
)

# Select it so the sidebar shows the dynamic controls immediately
api.select(dl)

# ============================================================== #
#  STAGED NODE EXAMPLE  (add without x/y, then place)            #
# ============================================================== #

t = api.add_node("Tensor", id="t")

if api.is_staged("t"):
    api.report.warning("Tensor is staged — placing now")
    api.place(t, -520, 460)
    api.report.success("Tensor placed at (-520, 460)")

if api.is_placed("smp"):
    api.report.debug("Sampler is on the canvas")

# ============================================================== #
#  READ BACK: ORDER + CODE                                       #
# ============================================================== #

print("\nTop → bottom:")
for n in api.nodes_by_position():
    print("  ", n.title)

print("\nDependency order (sources → sinks):")
for n in api.nodes_topo():
    print("  ", n.title)

print("\nPython lines:")
for line in api.code_lines():
    print("  ", line)

# ============================================================== #
#  EVENTS  (no lambdas)                                          #
# ============================================================== #

def on_node_added():
    api.report.info("A node was added")

def on_selection(nodes):
    titles = ", ".join(n.title for n in nodes) or "(none)"
    api.status(f"Selected: {titles}")

def on_edge_added():
    api.report.success("Connection made")

api.on("node_added", on_node_added)
api.on("selection",  on_selection)
api.on("edge_added", on_edge_added)

# ============================================================== #
#  OPTIONAL INTERACTIVE DEMO                                     #
# ============================================================== #

if api.picker.confirm("Run the interactive picker demo?", title="Picker Demo"):

    # --- register a new node on the fly ---
    name = api.picker.text("My Node", title="New node name", label="Name:")
    if name:
        color = api.picker.color("#4A8A5C", title="Pick a color") or "#3B3B3B"
        try:
            api.register_node(
                name, color=color, category="Custom",
                description="Registered via picker demo.",
                dynamic=True,                 # make it dynamic too
                inputs=[("A", "float", "First operand"),
                        ("B", "float", "Second operand")],
                outputs=[("Sum", "float", "A + B")],
            )
            api.report.success(f"Registered '{name}'")
        except ValueError as ex:
            api.report.error(str(ex))

        x = api.picker.number(200, -2000, 2000, decimals=0,
                              title="New node X", label="X:")
        y = api.picker.number(0,   -2000, 2000, decimals=0,
                              title="New node Y", label="Y:")
        if x is not None and y is not None:
            api.add_node(name, x=x, y=y, id="picked_node")
            api.report.success(f"Placed '{name}' at ({int(x)}, {int(y)})")

    # --- dynamic socket count via the picker ---
    target = api.picker.node(prompt="Click the node whose sockets you want to grow")
    if target:
        n_extra = api.picker.integer(3, 1, 50,
                                     title="Extra sockets",
                                     label="How many extra inputs?")
        if n_extra:
            for _ in range(int(n_extra)):
                target.add_socket(0, True)
            api.report.success(
                f"'{target.title}' now has {len(target.inputs)} inputs")

    # --- drop in a template ---
    tpl = api.picker.template(prompt="Pick a template to drop in")
    if tpl:
        api.add_node(tpl["name"], x=400, y=300)
        api.report.success(f"Added '{tpl['name']}'")

    # --- click a node, then one of its sockets ---
    picked = api.picker.node(prompt="Click any node (right-click to cancel)")
    if picked:
        api.report.info(f"You picked: {picked.title}")
        sock = api.picker.socket(
            node=picked, prompt=f"Click a socket on '{picked.title}'")
        if sock:
            direction = "input" if sock.is_input else "output"
            api.report.success(
                f"{picked.title}.{sock.name} ({direction}, {sock.socket_type})")

    # --- click a connection ---
    edge = api.picker.edge(prompt="Click a connection (right-click to cancel)")
    if edge and edge.start_socket and edge.end_socket:
        api.report.success(
            f"{edge.start_socket.node.title}.{edge.start_socket.name}  →  "
            f"{edge.end_socket.node.title}.{edge.end_socket.name}")

    # --- multi-pick ---
    multi = api.picker.nodes(prompt="Click several nodes · Enter to finish")
    if multi:
        api.report.info(
            "Multi-selected: " + ", ".join(n.title for n in multi))

    # --- generic dialogs ---
    num = api.picker.integer(30, 1, 200, title="Steps", label="Steps:")
    if num is not None:
        api.report.debug(f"Steps = {num}")

    choice = api.picker.choice(["euler", "dpm++", "heun", "ddim"],
                               title="Sampler method", label="Method:")
    if choice:
        api.report.debug(f"Method = {choice}")

    path = api.picker.file(
        title="Pick a model file",
        filt="Checkpoints (*.safetensors *.ckpt);;All Files (*)")
    if path:
        api.report.info(f"Model: {path}")

    out_path = api.picker.save_file(
        title="Export graph", default="pipeline.json", filt="JSON (*.json)")
    if out_path:
        api.save(out_path)      # already reports "Saved …" via api.save

    api.report.clear()
    api.report.info("Picker demo finished")

# ============================================================== #
#  FINAL DUMP + RUN                                              #
# ============================================================== #

print("\nFinal pipeline as code:")
for line in api.code_lines():
    print("  ", line)

api.report.info("Select 'Device List' — sidebar shows [+] [++] [−]",
                duration=6000)
api.report.info("Press Shift+A to add nodes · Middle-drag to pan",
                duration=6000)

api.app().exec_()