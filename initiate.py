"""
initiate.py — scaffold the community-health files for PyTorchUI.

Creates (or, with --force, overwrites):

    README.md
    CONTRIBUTING.md
    SECURITY.md
    CODE_OF_CONDUCT.md

By default, existing files are left untouched so re-running is safe.
Pass --force to overwrite, or --dry-run to preview without writing.

Usage:
    python3 initiate.py
    python3 initiate.py --force
    python3 initiate.py --dry-run
    python3 initiate.py --dir /path/to/project
"""

import argparse
import datetime
import os
import sys


# --------------------------------------------------------------------------- #
#  Content                                                                    #
# --------------------------------------------------------------------------- #

DATE = datetime.date.today().isoformat()


README = '''\
# PyTorchUI

<p align="center">
  <img src="https://raw.githubusercontent.com/OpenNoorIlm/PyTorchUI/main/docs/banner.png" alt="PyTorchUI" width="720">
</p>

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

MIT — see [LICENSE](LICENSE) if present.
'''


CONTRIBUTING = '''\
# Contributing to PyTorchUI

Thanks for taking the time to help. This document lays out what kinds of
contributions we want, how to send them, and what to expect in return.

## Ground rules

- Be kind. Read the [Code of Conduct](CODE_OF_CONDUCT.md) first.
- Open an issue before starting work on a large change. A five-minute
  conversation can save a weekend of rework.
- One change per pull request. Small PRs get reviewed fast.
- Tests are welcome but not required for UI tweaks — describe how you
  verified the change instead.

## Getting set up

```bash
git clone https://github.com/yourname/PyTorchUI.git
cd PyTorchUI
python -m venv .venv
source .venv/bin/activate
pip install PyQt5 matplotlib torch
python create.py
python main.py
```

If `main.py` fails to import, run the diagnostic:

```bash
python main.py 2>&1 | head -40
```

and open an issue with the output.

## What we're looking for

- **Bug fixes** with a clear reproduction.
- **New node types** that make a real workflow easier. Add them to the
  `ROLES` list in `helpers/Nodes/Nodes.py` with a sensible `kind`,
  `description`, and default values.
- **Improvements to `create.py`** — better type inference, more library
  filters, faster walking.
- **Documentation** — examples, tutorials, screenshots.
- **Test graphs** in `examples/` that exercise a feature end to end.

## Sending a pull request

1. Fork and branch:

   ```bash
   git checkout -b fix-codegen-splat
   ```

2. Make your changes.
3. Run the syntax check on anything you touched:

   ```bash
   python -m py_compile helpers/Nodes/Nodes.py create.py edit.py
   ```

4. Open the editor, load an example, press `Ctrl+G` and `F5`, and
   confirm nothing regressed.
5. Push and open a PR.

In the PR description, include:

- what the change does,
- why it's needed,
- how you tested it.

## Reporting bugs

Open an issue and include:

- what you did,
- what you expected,
- what actually happened,
- the output of `python -c "import sys; print(sys.version)"`,
- the output of `python -c "import torch; print(torch.__version__)"`,
- any traceback, in full.

If the bug is in codegen, paste the offending line from `generated.py`.

## Style

- Python 3.9+ syntax. No type annotations required, but welcome where
  they clarify.
- Four-space indents. Lines under 100 characters.
- Comments explain *why*, not *what*.
- No new third-party dependencies without a discussion first.

## License

By contributing, you agree your work is licensed under the project's
MIT license.
'''


SECURITY = '''\
# Security Policy

## Supported versions

PyTorchUI is alpha software. Only the latest commit on `main` receives
security fixes.

| version | supported |
| ------- | --------- |
| main    | yes       |
| older   | no        |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Instead, email the maintainer at `security@example.com` with:

- a description of the issue,
- steps to reproduce,
- the impact you believe it has,
- any suggested fix or mitigation.

You will get an acknowledgement within 72 hours. If the report is
accepted, we will:

1. Confirm the issue and its severity.
2. Prepare a fix on a private branch.
3. Credit you in the release notes unless you ask otherwise.

## Scope

PyTorchUI runs Python code that you construct in the editor. It does not
sandbox that code, and it is **not designed to execute untrusted graphs**.
Anything you load with **File → Open…** and run with **F5** runs with
your full user privileges — the same as running a Python script directly.

Concretely, this means:

- **In scope:** memory-safety bugs in the editor itself, path traversal
  in file loading, subprocess escaping, injection through graph JSON,
  or anything that lets one user's file harm another user's system.
- **Out of scope:** the fact that running a graph executes arbitrary
  code. That's the intended behaviour, and it is documented.

## Hardening tips for users

- Only open `*.json` graphs from sources you trust.
- Read `generated.py` before pressing `F5` if you are unsure what a
  graph does. `Ctrl+G` writes it and does not run anything.
- Run the editor in a virtualenv or container if you plan to load
  graphs from the internet.
- Keep `pip install --upgrade PyQt5 torch` current.

## Dependencies

PyQt5 and PyTorch are large upstream projects with their own security
policies. Vulnerabilities in those projects should be reported to them
directly:

- PyQt5: https://www.riverbankcomputing.com/software/pyqt/
- PyTorch: https://github.com/pytorch/pytorch/security/policy
'''


CODE_OF_CONDUCT = '''\
# Code of Conduct

## Our pledge

We as members, contributors, and leaders pledge to make participation in
our community a harassment-free experience for everyone, regardless of
age, body size, visible or invisible disability, ethnicity, sex
characteristics, gender identity and expression, level of experience,
education, socio-economic status, nationality, personal appearance,
race, religion, or sexual identity and orientation.

We pledge to act and interact in ways that contribute to an open,
welcoming, diverse, inclusive, and healthy community.

## Our standards

Examples of behaviour that contributes to a positive environment:

- Demonstrating empathy and kindness toward other people.
- Being respectful of differing opinions, viewpoints, and experiences.
- Giving and gracefully accepting constructive feedback.
- Accepting responsibility and apologising to those affected by our
  mistakes, and learning from the experience.
- Focusing on what is best not just for us as individuals, but for the
  overall community.

Examples of unacceptable behaviour:

- The use of sexualised language or imagery, and sexual attention or
  advances of any kind.
- Trolling, insulting or derogatory comments, and personal or political
  attacks.
- Public or private harassment.
- Publishing others' private information, such as a physical or email
  address, without their explicit permission.
- Other conduct which could reasonably be considered inappropriate in a
  professional setting.

## Enforcement responsibilities

Community leaders are responsible for clarifying and enforcing our
standards of acceptable behaviour and will take appropriate and fair
corrective action in response to any behaviour that they deem
inappropriate, threatening, offensive, or harmful.

Community leaders have the right and responsibility to remove, edit, or
reject comments, commits, code, wiki edits, issues, and other
contributions that are not aligned to this Code of Conduct, and will
communicate reasons for moderation decisions when appropriate.

## Scope

This Code of Conduct applies within all community spaces, and also
applies when an individual is officially representing the community in
public spaces.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behaviour may
be reported to the community leaders responsible for enforcement at
`conduct@example.com`. All complaints will be reviewed and investigated
promptly and fairly.

All community leaders are obligated to respect the privacy and security
of the reporter of any incident.

## Enforcement guidelines

Community leaders will follow these Community Impact Guidelines in
determining the consequences for any action they deem in violation of
this Code of Conduct:

### 1. Correction

**Community impact:** Use of inappropriate language or other behaviour
deemed unprofessional or unwelcome in the community.

**Consequence:** A private, written warning from community leaders,
providing clarity around the nature of the violation and an explanation
of why the behaviour was inappropriate. A public apology may be
requested.

### 2. Warning

**Community impact:** A violation through a single incident or series of
actions.

**Consequence:** A warning with consequences for continued behaviour. No
interaction with the people involved, including unsolicited interaction
with those enforcing the Code of Conduct, for a specified period of
time. This includes avoiding interactions in community spaces as well as
external channels like social media. Violating these terms may lead to a
temporary or permanent ban.

### 3. Temporary ban

**Community impact:** A serious violation of community standards,
including sustained inappropriate behaviour.

**Consequence:** A temporary ban from any sort of interaction or public
communication with the community for a specified period of time. No
public or private interaction with the people involved, including
unsolicited interaction with those enforcing the Code of Conduct, is
allowed during this period. Violating these terms may lead to a
permanent ban.

### 4. Permanent ban

**Community impact:** Demonstrating a pattern of violation of community
standards, including sustained inappropriate behaviour, harassment of an
individual, or aggression toward or disparagement of classes of
individuals.

**Consequence:** A permanent ban from any sort of public interaction
within the community.

## Attribution

This Code of Conduct is adapted from the
[Contributor Covenant](https://www.contributor-covenant.org), version
2.1, available at
https://www.contributor-covenant.org/version/2/1/code_of_conduct.html.

Community Impact Guidelines were inspired by
[Mozilla's code of conduct enforcement ladder](https://github.com/mozilla/diversity).

For answers to common questions about this code of conduct, see the FAQ
at https://www.contributor-covenant.org/faq.
'''


FILES = [
    ("README.md",          README),
    ("CONTRIBUTING.md",    CONTRIBUTING),
    ("SECURITY.md",        SECURITY),
    ("CODE_OF_CONDUCT.md", CODE_OF_CONDUCT),
]


# --------------------------------------------------------------------------- #
#  Main                                                                       #
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(
        prog="initiate.py",
        description="Scaffold README.md, CONTRIBUTING.md, SECURITY.md, "
                    "and CODE_OF_CONDUCT.md for PyTorchUI.",
    )
    parser.add_argument(
        "-d", "--dir", dest="target_dir", default=".",
        help="directory to write into (default: current directory)",
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="overwrite existing files",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="show what would happen without writing anything",
    )
    args = parser.parse_args()

    target = os.path.abspath(args.target_dir)
    if not os.path.isdir(target):
        print("! target directory does not exist: %s" % target)
        sys.exit(1)

    print("Target: %s" % target)
    print()

    written = 0
    skipped = 0

    for name, content in FILES:
        full = os.path.join(target, name)
        exists = os.path.isfile(full)

        if exists and not args.force:
            print("  --  %-22s exists, skipped" % name)
            skipped += 1
            continue

        if args.dry_run:
            verb = "would overwrite" if exists else "would create"
            print("  ok  %-22s %s (%d bytes)"
                  % (name, verb, len(content)))
            written += 1
            continue

        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        verb = "overwrote" if exists else "created"
        print("  [+] %-22s %s (%d bytes)"
              % (name, verb, len(content)))
        written += 1

    print()
    if args.dry_run:
        print("Dry run: %d file(s) would change, %d left alone."
              % (written, skipped))
    else:
        print("Done.  %d file(s) written, %d left alone."
              % (written, skipped))
        if skipped and not args.force:
            print()
            print("Existing files were preserved.  Pass --force to")
            print("overwrite them.")


if __name__ == "__main__":
    main()
