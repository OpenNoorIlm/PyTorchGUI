#!/usr/bin/env python3
"""
cleanup_repo.py — tidy up the repo root.

Moves:
    test.py         -> tests/test.py
    pipeline.json   -> examples/pipeline.json

Appends stray-file ignore rules to .gitignore.

By default this is a dry run.  Pass --apply to make the changes and
--commit to stage + commit them afterward.  Nothing is deleted; every
move is a `git mv` if the file is tracked, otherwise a filesystem move.
"""

import argparse
import os
import shutil
import subprocess
import sys


# (source, destination)
MOVES = [
    ("test.py",       "tests/test.py"),
    ("pipeline.json", "examples/pipeline.json"),
]


# Flagged but not touched.
NOTES = [
    ("examples.py",
     "shadows the examples/ directory name; consider renaming to "
     "make_examples.py"),
    ("createGit.py",
     "verify the intended name — the scaffolder was createGitIgnore.py"),
    ("edit.py",
     "one-off patch script; consider moving to scripts/"),
    ("editGit.py",
     "one-off patch script; consider moving to scripts/"),
]


GITIGNORE_BLOCK = """
# ---------------------------------------------------------------- #
#  Stray scratch files                                              #
# ---------------------------------------------------------------- #

# A saved graph at the repo root — belongs under examples/.
/pipeline.json

# Ad-hoc scripts at the root.  Real tests belong in tests/.
/test.py
/scratch/
/tmp/
*.log
*.tmp
"""


def is_git_repo():
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"],
                       capture_output=True, check=True)
        return True
    except Exception:
        return False


def tracked(path):
    r = subprocess.run(["git", "ls-files", "--error-unmatch", path],
                       capture_output=True)
    return r.returncode == 0


def move_file(src, dst, apply):
    if not os.path.exists(src):
        print("  --  %-24s not present, skipping" % src)
        return "skip"
    if os.path.exists(dst):
        print("  !!  %-24s destination already exists: %s"
              % (src, dst))
        return "conflict"

    print("  %-11s %-24s -> %s"
          % ("moving" if apply else "would move", src, dst))

    if apply:
        d = os.path.dirname(dst)
        if d:
            os.makedirs(d, exist_ok=True)
        if is_git_repo() and tracked(src):
            subprocess.run(["git", "mv", src, dst], check=True)
        else:
            shutil.move(src, dst)
    return "moved"


def update_gitignore(apply):
    path = ".gitignore"
    existing = ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()

    if "/pipeline.json" in existing and "/scratch/" in existing:
        print("  [ok] .gitignore already has the extra rules")
        return 0

    block = GITIGNORE_BLOCK.rstrip() + "\n"
    new = existing.rstrip() + "\n" + block

    if apply:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        print("  [+] .gitignore updated")
    else:
        print("  ok  would append to .gitignore:")
        for line in block.strip().split("\n"):
            print("      %s" % line)
    return 1


def show_notes():
    found = [(n, msg) for (n, msg) in NOTES if os.path.exists(n)]
    if not found:
        return
    print("Notes (left alone):")
    for n, msg in found:
        print("  ~   %-16s %s" % (n, msg))


def main():
    p = argparse.ArgumentParser(
        prog="cleanup_repo.py",
        description="Tidy up the PyTorchUI repo root.",
    )
    p.add_argument("--apply", action="store_true",
                   help="perform the changes (default is a dry run)")
    p.add_argument("--commit", action="store_true",
                   help="git add + commit afterward")
    p.add_argument("--no-gitignore", action="store_true",
                   help="skip the .gitignore update")
    args = p.parse_args()

    if not os.path.isdir(".git") and not os.path.isfile(".gitignore"):
        print("This doesn't look like the PyTorchUI project root.")
        print("Run from the directory containing .git/ and .gitignore.")
        sys.exit(1)

    print("Project: %s" % os.path.abspath("."))
    print("Mode:    %s" % ("APPLY" if args.apply else "dry run"))
    print()

    print("Moving stray files:")
    for src, dst in MOVES:
        move_file(src, dst, args.apply)

    print()
    if not args.no_gitignore:
        print("Updating .gitignore:")
        update_gitignore(args.apply)

    print()
    show_notes()

    if args.apply and args.commit:
        print()
        print("Committing:")
        subprocess.run(["git", "add", "-A"], check=True)
        r = subprocess.run(
            ["git", "commit", "-m",
             "chore: tidy repo root — move stray files, update .gitignore"],
            capture_output=True, text=True)
        if r.returncode == 0:
            print("  [+] committed")
        else:
            print("  ! commit failed: %s" % r.stderr.strip())

    print()
    if args.apply:
        print("Done.  Review with:")
        print("    git status")
        print("    git log --oneline -1")
    else:
        print("Dry run.  Re-run with --apply to make the changes.")


if __name__ == "__main__":
    main()