"""Check the collect job's output, then copy it into the repository.

The job that reads third-party pages holds no write access. What it produced
is handed to the publish job as an artifact, and this is the gate between
the two: only the pipeline's own output files may pass, in the shapes the
pipeline writes them, so a compromised collect run can at worst put wrong
text in a data file. It cannot add a workflow, change the site's code or
drop a file anywhere else in the repository.

    python -m steward.publish OUTPUT_DIR REPO_DIR

Standard library only: the publish job runs it without installing anything.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Iterable, List, Tuple

# What the pipeline writes. Keep in step with the collect job's
# upload-artifact paths in .github/workflows/update_checker.yml.
FILES = ("hashes.json", "health.json", "history.json", "runs.jsonl")
DIRECTORIES = ("analysis", "diffs", "snapshots", "logs", "news", "transparency")
SUFFIXES = (".json", ".jsonl", ".txt", ".diff")

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024


class RejectedOutput(ValueError):
    """The output contains something the pipeline does not write."""


def check(output_dir: str) -> List[str]:
    """Every file under output_dir, as relative paths, or raise RejectedOutput."""
    problems: List[str] = []
    accepted: List[str] = []
    total = 0
    for relative, full in _walk(output_dir):
        parts = relative.split("/")
        where = parts[0]
        if os.path.islink(full):
            problems.append(f"{relative}: symbolic links are not pipeline output")
            continue
        if not os.path.isfile(full):
            problems.append(f"{relative}: not a regular file")
            continue
        if len(parts) == 1 and where not in FILES:
            problems.append(f"{relative}: not a file the pipeline writes")
            continue
        if len(parts) > 1 and where not in DIRECTORIES:
            problems.append(f"{relative}: not in a directory the pipeline writes")
            continue
        if any(part.startswith(".") for part in parts):
            problems.append(f"{relative}: hidden files are not pipeline output")
            continue
        if not relative.endswith(SUFFIXES):
            problems.append(f"{relative}: unexpected file type")
            continue
        size = os.path.getsize(full)
        total += size
        if size > MAX_FILE_BYTES:
            problems.append(f"{relative}: {size:,} bytes is over the {MAX_FILE_BYTES:,} byte limit")
            continue
        problem = _content_problem(full, relative)
        if problem:
            problems.append(problem)
            continue
        accepted.append(relative)
    if total > MAX_TOTAL_BYTES:
        problems.append(f"output totals {total:,} bytes, over the {MAX_TOTAL_BYTES:,} byte limit")
    if not any(name in FILES for name in accepted):
        problems.append("output has none of the pipeline's state files; the collect job did not run")
    if problems:
        raise RejectedOutput("\n".join(problems))
    return accepted


def copy_into(output_dir: str, repo_dir: str) -> None:
    """Replace the repository's copies with the checked output.

    A directory present in the output replaces the repository's wholesale, so
    files the pipeline deleted (pruned logs, a withdrawn statement) go too. A
    directory or file missing from the output is left as it is.
    """
    check(output_dir)
    for name in DIRECTORIES:
        source = os.path.join(output_dir, name)
        if os.path.isdir(source):
            target = os.path.join(repo_dir, name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(source, target, symlinks=False)
    for name in FILES:
        source = os.path.join(output_dir, name)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(repo_dir, name))


def _walk(root: str) -> Iterable[Tuple[str, str]]:
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        for name in subdirectories + files:
            full = os.path.join(directory, name)
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            if name in subdirectories and not os.path.islink(full):
                continue
            yield relative, full


def _content_problem(full: str, relative: str) -> str:
    try:
        with open(full, "r", encoding="utf-8") as handle:
            text = handle.read()
    except UnicodeDecodeError:
        return f"{relative}: not UTF-8 text"
    try:
        if relative.endswith(".json"):
            json.loads(text)
        elif relative.endswith(".jsonl"):
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
    except json.JSONDecodeError as exc:
        return f"{relative}: not valid JSON ({exc})"
    return ""


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m steward.publish OUTPUT_DIR REPO_DIR", file=sys.stderr)
        return 2
    try:
        copy_into(argv[0], argv[1])
    except RejectedOutput as exc:
        print(f"::error title=Pipeline output rejected::{exc}".replace("\n", "%0A"))
        return 1
    print("Pipeline output checked and copied into place.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
