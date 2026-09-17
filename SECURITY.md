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
