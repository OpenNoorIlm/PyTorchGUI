# PyTorchUI

A Blender-styled node editor for building and running PyTorch pipelines
visually. Drag nodes onto a canvas, wire them together, and press **Run**
to execute the generated Python.

![status](https://img.shields.io/badge/status-alpha-orange)

## Features

- **Visual graph editor.** Rounded Blender-style nodes, typed sockets,
  bezier edges, section folding, block nesting.
- **Live codegen.** `Ctrl+G` writes `generated.py` from whatever is on
  the canvas. Every node maps to real Python.
- **Streamed execution.** `F5` runs `generated.py` in a subprocess and
  streams each node's stdout back into that node's shell strip.
- **Pause / Resume / Stop.** `Ctrl+F5`, `Ctrl+Shift+F5`, `Shift+F5` —
  SIGSTOP / SIGCONT / SIGKILL to the subprocess, editor stays responsive.
- **Input dialog.** `input` nodes surface a `QInputDialog` during the run.
- **Generated library.** `create.py` walks torch (and any library you
  pass with `-l`) and emits `main.py` with a node for every class and
  function it finds.
- **Documented.** Hover anything for a summary; `F1` opens the help
  dock with full docs, LaTeX math, and Python / C++ syntax highlighting.
- **Persistent settings.** Window geometry, splitter sizes, auto-save
  interval, and every toggle are stored in `~/.pytorchui/settings.json`.

## Requirements

- Python 3.9+
- PyQt5
- matplotlib (for the help dock's math renderer)
- PyTorch (for the generated node library)

```bash
pip install PyQt5 matplotlib torch
```

## Install

```bash
git clone https://github.com/yourname/PyTorchUI.git
cd PyTorchUI
pip install -r requirements.txt    # if you have one
```

## Quick start

```bash
# 1. Build the generated node library from your installed torch.
python create.py                    # torch only
python create.py -l os json math    # torch + a few stdlib modules

# 2. Launch the editor.
python main.py
```

Inside the editor:

| key | action |
| --- | --- |
| `Shift+A` | open the Add-node popup |
| `Ctrl+G` | generate `generated.py` from the current graph |
| `F5` | run `generated.py` |
| `Ctrl+F5` | pause the running subprocess |
| `Ctrl+Shift+F5` | resume |
| `Shift+F5` | stop |
| `Ctrl+E` | browse example pipelines |
| `F1` | toggle the help dock |
| `Del` | delete the selection |
| `Ctrl+D` | duplicate the selection |
| `Home` | frame all nodes |
| middle-drag | pan |
| wheel | zoom |

## Examples

Open any file in `examples/` via **File → Open…**:

- `01_hello.json` — minimal Start → tensor → print
- `02_cnn.json` — a small CNN built from `nn.*` modules
- `03_training_step.json` — forward pass through a CNN, `CrossEntropyLoss`
- `11_function.json` — `def square(n): return n * n` plus a call site
- `13_class.json` — a `Point` class with `__init__` and `dist`

## Project layout

```
PyTorchUI/
├── create.py             # generates main.py from installed libraries
├── edit.py               # patch helpers for Nodes.py / main.py
├── main.py               # generated node library + editor bootstrap
├── helpers/
│   └── Nodes/
│       └── Nodes.py      # the editor: canvas, codegen, runtime
├── examples/             # sample graphs
└── generated.py          # emitted by the editor on Ctrl+G
```

## How it works

1. `create.py` imports each requested library and walks it with
   `pkgutil.walk_packages`, collecting every public class and function
   into a `SPECS` list, which it writes into `main.py`.
2. `main.py` registers each spec as a node template with `api.register.node.bulk`.
3. When you press `Ctrl+G`, `Nodes.py` walks the graph, emits Python for
   each node in topological order, and writes `generated.py`.
4. When you press `F5`, the editor spawns `generated.py` in a subprocess
   with `start_new_session=True`, reads its stdout line by line, and
   routes `@@RT` markers back to the nodes they came from.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md).

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Copyright (C) 2026 the PyTorchUI authors

This program is free software: you can redistribute it and/or modify
it under the terms of the **GNU General Public License** as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
**without any warranty**; without even the implied warranty of
merchantability or fitness for a particular purpose. See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see
<https://www.gnu.org/licenses/>.

See [LICENSE](LICENSE) for the full text.
