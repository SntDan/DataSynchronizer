"""Persistent gitignore-style rules shared by scanning and synchronization."""

import os
from pathlib import Path

from pathspec import GitIgnoreSpec


DEFAULT_IGNORE_TEXT = """# DataSynchronizer ignore rules (relative to each path pair).
# Supports gitignore syntax: *, **, ?, /folder/, and !exceptions.
# Ignored items are displayed in gray and never copied or deleted.
Thumbs.db
thumbs.db
desktop.ini
Desktop.ini
.DS_Store
$RECYCLE.BIN/
"""


class IgnoreRules:
    def __init__(self, lines=()):
        # Windows paths are case insensitive, including user-written rules.
        lines = list(lines)
        if os.name == "nt":
            lines = [line.lower() for line in lines]
        self.spec = GitIgnoreSpec.from_lines(lines)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            path.write_text(DEFAULT_IGNORE_TEXT, encoding="utf-8")
        return cls(path.read_text(encoding="utf-8-sig").splitlines())

    def matches(self, rel_path, is_directory=False):
        path = rel_path.replace("\\", "/").strip("/")
        if os.name == "nt":
            path = path.lower()
        # A pruned directory cannot be re-included through a child exception.
        parts = path.split("/")
        for index in range(1, len(parts)):
            if self.spec.match_file("/".join(parts[:index]) + "/"):
                return True
        return self.spec.match_file(path + ("/" if is_directory else ""))


def append_ignore_path(path, rel_path, is_directory=False):
    """Append an anchored literal rule, escaping pattern characters."""
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("This path cannot be represented in an ignore file")
    escaped = "".join(
        "\\" + char if char in "*?[]#! " else char
        for char in normalized
    )
    rule = "/" + escaped + ("/" if is_directory else "")
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig") if path.exists() else DEFAULT_IGNORE_TEXT
    # Append even if an earlier identical rule exists: a later ! rule may undo it.
    path.write_text(text + ("" if text.endswith("\n") else "\n") + rule + "\n", encoding="utf-8")


def apply_ignore_rules(differences, rules):
    """Protect ignored descendants before a mirror directory deletion."""
    ignored = {}
    for item in differences:
        if item[0] in ("IGNORED", "IGNORED_DIR"):
            ignored.setdefault((item[4], item[5]), {})[
                item[1].replace("\\", "/")
            ] = item[0] == "IGNORED_DIR"
    result = {}
    protected = {}
    for item in differences:
        status, rel_path = item[:2]
        normalized = rel_path.replace("\\", "/")
        pair = (item[4], item[5])
        ignored_paths = ignored.get(pair, {})
        covered = normalized in ignored_paths
        parent = normalized.rpartition("/")[0]
        while parent and not covered:
            covered = ignored_paths.get(parent, False)
            parent = parent.rpartition("/")[0]
        is_directory = status in ("EXTRA_DIR", "IGNORED_DIR", "PRESERVED_DIR")
        if covered or rules.matches(rel_path, is_directory):
            status = "IGNORED_DIR" if is_directory else "IGNORED"
            item = (status, *item[1:])
        if status in ("IGNORED", "IGNORED_DIR", "PRESERVED_DIR"):
            ancestors = protected.setdefault((item[4], item[5]), set())
            parent = rel_path.replace("\\", "/").rpartition("/")[0]
            while parent:
                ancestors.add(parent)
                parent = parent.rpartition("/")[0]
        result[(pair, normalized)] = item
    return [
        ("PRESERVED_DIR", *item[1:])
        if item[0] == "EXTRA_DIR"
        and item[1].replace("\\", "/") in protected.get((item[4], item[5]), ())
        else item
        for item in result.values()
    ]
