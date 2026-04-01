import difflib
import re
from typing import Union


def compute_unified_diff(
    content_a: Union[bytes, str],
    content_b: Union[bytes, str],
    filename: str,
    from_label: str = "before",
    to_label: str = "after",
) -> str:
    """Produce a unified diff string between two file contents.

    Returns an empty string if the contents are identical or if either
    side cannot be decoded as text.
    """
    def to_lines(raw):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return raw.splitlines(keepends=True)

    lines_a = to_lines(content_a)
    lines_b = to_lines(content_b)

    diff = difflib.unified_diff(
        lines_a,
        lines_b,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        fromfiledate=from_label,
        tofiledate=to_label,
        lineterm="",
    )
    return "\n".join(diff)


def parse_diff_lines(diff_text: str) -> list[dict]:
    """Parse a unified diff string into annotated line dicts for template rendering.

    Each dict has:
        type     : 'meta' | 'hunk' | 'add' | 'remove' | 'context'
        content  : str — raw line text without the leading +/-/space
        line_old : int | None — 1-based line number in the "from" file
        line_new : int | None — 1-based line number in the "to" file

    Returns [] for an empty or whitespace-only diff_text.
    """
    if not diff_text.strip():
        return []

    result = []
    old_lineno = None
    new_lineno = None

    for line in diff_text.split("\n"):
        line = line.rstrip("\r")

        if line.startswith("--- ") or line.startswith("+++ "):
            result.append({"type": "meta", "content": line, "line_old": None, "line_new": None})
            continue

        if line.startswith("@@ "):
            m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                old_lineno = int(m.group(1))
                new_lineno = int(m.group(2))
            result.append({"type": "hunk", "content": line, "line_old": None, "line_new": None})
            continue

        if line.startswith("+"):
            result.append({"type": "add", "content": line[1:], "line_old": None, "line_new": new_lineno})
            if new_lineno is not None:
                new_lineno += 1
            continue

        if line.startswith("-"):
            result.append({"type": "remove", "content": line[1:], "line_old": old_lineno, "line_new": None})
            if old_lineno is not None:
                old_lineno += 1
            continue

        # Context line (leading space) or trailing blank
        content = line[1:] if line.startswith(" ") else line
        result.append({"type": "context", "content": content, "line_old": old_lineno, "line_new": new_lineno})
        if old_lineno is not None:
            old_lineno += 1
        if new_lineno is not None:
            new_lineno += 1

    return result
