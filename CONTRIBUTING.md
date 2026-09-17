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

PyTorchUI is released under the **GNU General Public License v3.0**
(or, at your option, any later version). See [LICENSE](LICENSE) for the
full text.

By opening a pull request you agree that your contribution is licensed
under the same terms. If you are contributing on behalf of an employer,
please ensure you have the authority to do so.
