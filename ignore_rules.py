"""Persistent gitignore-style rules shared by scanning and synchronization."""

import os
import json
from pathlib import Path

from pathspec import GitIgnoreSpec


DEFAULT_IGNORE_TEXT = """# DataSynchronizer ignore rules (relative to each path pair).
# Supports gitignore syntax: *, **, ?, /folder/, and !exceptions.
# Global exclusions are hidden; pair exclusions are displayed in gray.
# @global
Thumbs.db
thumbs.db
desktop.ini
Desktop.ini
.DS_Store
$RECYCLE.BIN/
"""


class IgnoreRules:
    def __init__(self, lines=(), *, global_lines=(), pair_lines=None):
        self.global_lines = list(global_lines)
        self.global_spec = self._compile(self.global_lines)
        self.spec = self._compile(lines)
        self.pair_lines = pair_lines
        self._pairs = {}

    @staticmethod
    def _compile(lines):
        # Windows paths are case insensitive, including user-written rules.
        lines = list(lines)
        if os.name == "nt":
            lines = [line.lower() for line in lines]
        return GitIgnoreSpec.from_lines(lines)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            path.write_text(DEFAULT_IGNORE_TEXT, encoding="utf-8")
        global_lines, pairs = [], {}
        current_lines = global_lines
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            marker = line.strip()
            if marker == "# @global":
                current_lines = global_lines
            elif marker.startswith("# @pair "):
                pair = json.loads(marker[len("# @pair "):])
                if (
                    not isinstance(pair, dict)
                    or not isinstance(pair.get("source"), str) or not pair["source"]
                    or not isinstance(pair.get("target"), str) or not pair["target"]
                    or not isinstance(pair.get("target_is_file", False), bool)
                ):
                    raise ValueError("Invalid # @pair header: source and target paths are required")
                key = path_pair_key(pair["source"], pair["target"], pair.get("target_is_file", False))
                current_lines = pairs.setdefault(key, [])
            else:
                current_lines.append(line)
        return cls(global_lines=global_lines, pair_lines=pairs)

    def for_pair(self, source, target, target_is_file=False):
        if self.pair_lines is None:
            return self
        key = (source, target, target_is_file)
        if key not in self._pairs:
            lines = self.pair_lines.get(path_pair_key(source, target, target_is_file), ())
            self._pairs[key] = IgnoreRules(lines, global_lines=self.global_lines)
        return self._pairs[key]

    def global_matches(self, rel_path, is_directory=False):
        return self._matches(self.global_spec, rel_path, is_directory)

    def matches(self, rel_path, is_directory=False):
        return self.global_matches(rel_path, is_directory) or self._matches(self.spec, rel_path, is_directory)

    @staticmethod
    def _matches(spec, rel_path, is_directory):
        path = rel_path.replace("\\", "/").strip("/")
        if os.name == "nt":
            path = path.lower()
        # A pruned directory cannot be re-included through a child exception.
        parts = path.split("/")
        for index in range(1, len(parts)):
            if spec.match_file("/".join(parts[:index]) + "/"):
                return True
        return spec.match_file(path + ("/" if is_directory else ""))


def path_pair_key(source, target, target_is_file=False):
    return (
        os.path.normcase(os.path.normpath(os.path.abspath(source))),
        os.path.normcase(os.path.normpath(os.path.abspath(target))),
        bool(target_is_file),
    )


def append_ignore_path(path, rel_path, is_directory=False, *, pair=None):
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
    # Validate existing scope headers before modifying the user's rules.
    if path.exists():
        IgnoreRules.load(path)
    if pair is None:
        header = "# @global"
    else:
        source, target, target_is_file = pair
        source, target, target_is_file = path_pair_key(source, target, target_is_file)
        header = "# @pair " + json.dumps(
            {"source": source, "target": target, "target_is_file": target_is_file}, ensure_ascii=False
        )
    # Append even if an earlier identical rule exists: a later ! rule may undo it.
    path.write_text(text + ("" if text.endswith("\n") else "\n") + header + "\n" + rule + "\n", encoding="utf-8")


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
        pair_rules = rules.for_pair(*pair, item[7] if len(item) >= 8 else False)
        ignored_paths = ignored.get(pair, {})
        covered = normalized in ignored_paths
        parent = normalized.rpartition("/")[0]
        while parent and not covered:
            covered = ignored_paths.get(parent, False)
            parent = parent.rpartition("/")[0]
        is_directory = status in ("EXTRA_DIR", "IGNORED_DIR", "PRESERVED_DIR")
        global_ignored = pair_rules.global_matches(rel_path, is_directory)
        if global_ignored or covered or pair_rules.matches(rel_path, is_directory):
            status = "IGNORED_DIR" if is_directory else "IGNORED"
            item = (status, *item[1:])
        if status in ("IGNORED", "IGNORED_DIR", "PRESERVED_DIR", "READ_ONLY"):
            ancestors = protected.setdefault((item[4], item[5]), set())
            parent = rel_path.replace("\\", "/").rpartition("/")[0]
            while parent:
                ancestors.add(parent)
                parent = parent.rpartition("/")[0]
        if not global_ignored:
            result[(pair, normalized)] = item
    return [
        ("PRESERVED_DIR", *item[1:])
        if item[0] == "EXTRA_DIR"
        and item[1].replace("\\", "/") in protected.get((item[4], item[5]), ())
        else item
        for item in result.values()
    ]
