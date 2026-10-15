"""Persistent gitignore-style rules shared by scanning and synchronization."""

import os
import json
from functools import lru_cache
from pathlib import Path

from pathspec import GitIgnoreSpec
from storage import write_text_atomic


COPY_STATE_DIRECTORY = ".ds-sync"


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


def relative_path_key(path):
    path = path.replace("\\", "/")
    return path.lower() if os.name == "nt" else path


class IgnoreRules:
    def __init__(self, lines=(), *, global_lines=(), pair_lines=None):
        self.global_lines = list(global_lines)
        self.global_spec = self._compile(self.global_lines)
        self.spec = self._compile(lines)
        # Siblings share directory prefixes; bound both caches for large scans.
        self._global_directory_matches = lru_cache(maxsize=4096)(self.global_spec.match_file)
        self._pair_directory_matches = lru_cache(maxsize=4096)(self.spec.match_file)
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
            write_text_atomic(path, DEFAULT_IGNORE_TEXT)
        return cls.from_text(path.read_text(encoding="utf-8-sig"))

    @classmethod
    def from_text(cls, text):
        global_lines, pairs = [], {}
        current_lines = global_lines
        for line in text.splitlines():
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
        # This reserved work directory is protected independently of user
        # patterns, including exception rules that would otherwise re-include it.
        path = "/" + relative_path_key(rel_path).strip("/") + ("/" if is_directory else "")
        if f"/{COPY_STATE_DIRECTORY}/" in path:
            return True
        return self._matches(self.global_spec, self._global_directory_matches, rel_path, is_directory)

    def pair_matches(self, rel_path, is_directory=False):
        return self._matches(self.spec, self._pair_directory_matches, rel_path, is_directory)

    def matches(self, rel_path, is_directory=False):
        return self.global_matches(rel_path, is_directory) or self.pair_matches(rel_path, is_directory)

    @staticmethod
    def _matches(spec, directory_matches, rel_path, is_directory):
        if not spec.patterns:
            return False
        path = relative_path_key(rel_path).strip("/")
        # A pruned directory cannot be re-included through a child exception.
        parts = path.split("/")
        for index in range(1, len(parts)):
            if directory_matches("/".join(parts[:index]) + "/"):
                return True
        return directory_matches(path + "/") if is_directory else spec.match_file(path)


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
    if pair is None:
        header = "# @global"
    else:
        source, target, target_is_file = pair
        source, target, target_is_file = path_pair_key(source, target, target_is_file)
        header = "# @pair " + json.dumps(
            {"source": source, "target": target, "target_is_file": target_is_file}, ensure_ascii=False
        )
    # Append even if an earlier identical rule exists: a later ! rule may undo it.
    text += ("" if text.endswith("\n") else "\n") + header + "\n" + rule + "\n"
    rules = IgnoreRules.from_text(text)
    write_text_atomic(path, text)
    return rules


def apply_ignore_rules(differences, rules, cancel_event=None):
    """Protect ignored descendants before a mirror directory deletion."""
    ignored = {}
    for item in differences:
        if cancel_event is not None and cancel_event.is_set():
            return []
        if item[0] in ("IGNORED", "IGNORED_DIR"):
            ignored.setdefault((item[4], item[5]), {})[
                relative_path_key(item[1])
            ] = item[0] == "IGNORED_DIR"
    result = {}
    protected = {}
    for item in differences:
        if cancel_event is not None and cancel_event.is_set():
            return []
        status, rel_path = item[:2]
        normalized = relative_path_key(rel_path)
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
        if global_ignored or covered or pair_rules.pair_matches(rel_path, is_directory):
            status = "IGNORED_DIR" if is_directory else "IGNORED"
            item = (status, *item[1:])
        if status in ("IGNORED", "IGNORED_DIR", "PRESERVED_DIR", "READ_ONLY"):
            ancestors = protected.setdefault((item[4], item[5]), set())
            parent = normalized.rpartition("/")[0]
            while parent:
                ancestors.add(parent)
                parent = parent.rpartition("/")[0]
        if not global_ignored:
            result[(pair, normalized)] = item
    return [
        ("PRESERVED_DIR", *item[1:])
        if item[0] == "EXTRA_DIR"
        and relative_path_key(item[1]) in protected.get((item[4], item[5]), ())
        else item
        for item in result.values()
    ]
