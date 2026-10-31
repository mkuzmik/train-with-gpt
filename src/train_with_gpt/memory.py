"""Coach memory: the coach's own undated, editable working knowledge about an athlete.

One Markdown file per memory, in `memory/` (personal path) or
`memory/<user_id>/` (hosted), named `<name>.md`. A file starts with a small
front matter block holding the memory's category and one-line description:

    ---
    category: Science
    description: Polarized base block, sources and how it's working
    ---

    <the memory's body>

The index (one line per memory, grouped by category) is built from these
files whenever it's read, so there's no separate index file to fall out of
sync. Memories carry no dates: they're updated in place or deleted.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_CATEGORY = "Other"
SUGGESTED_CATEGORIES = ("Science", "Coaching approach", "Open threads", "Data and vocabulary")

# The memory that tracks the one-time backfill from consultation notes
# (build_memory_from_notes); start_consultation looks for it by name.
BACKFILL_MEMORY_NAME = "notes-backfill"

NAME_MAX_CHARS = 60
CATEGORY_MAX_CHARS = 40
DESCRIPTION_MAX_CHARS = 150

# How many index entries start_consultation loads. Storage has no limit; only
# this loaded index is capped (read_memory_index always returns everything).
INDEX_LOAD_LIMIT = 100

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)


class MemoryRequestError(ValueError):
    """A memory request that can't be carried out; the message is for the model."""


@dataclass
class Memory:
    name: str
    category: str
    description: str
    body: str


def count_memories(count: int) -> str:
    """"1 memory", "3 memories"."""
    return f"{count} {'memory' if count == 1 else 'memories'}"


# --- names, categories, descriptions -------------------------------------------------

def suggest_name(text: str) -> str:
    """A valid memory name close to `text` (lowercase words joined by hyphens)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:NAME_MAX_CHARS].strip("-")


def normalize_name(name) -> str:
    """The memory name as stored (lowercased), or MemoryRequestError if it isn't a valid one."""
    if not isinstance(name, str) or not name.strip():
        raise MemoryRequestError("No memory name provided.")
    normalized = name.strip().lower()
    if len(normalized) > NAME_MAX_CHARS or not _NAME_RE.match(normalized):
        suggestion = suggest_name(name)
        hint = f" e.g. `{suggestion}`" if suggestion else ""
        raise MemoryRequestError(
            f"Invalid memory name {name.strip()[:80]!r}: use lowercase letters, digits and single "
            f"hyphens, at most {NAME_MAX_CHARS} characters,{hint}."
        )
    return normalized


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def normalize_description(description) -> str:
    text = _one_line(description)
    if not text:
        raise MemoryRequestError("No description provided: give a one-line summary for the index.")
    if len(text) > DESCRIPTION_MAX_CHARS:
        raise MemoryRequestError(
            f"The description is {len(text)} characters, over the {DESCRIPTION_MAX_CHARS} limit: it's one "
            "line in the index, so shorten it and put the detail in the memory's content."
        )
    return text


def normalize_category(category, existing: list[str]) -> str:
    """One line, or "Other" when empty; reuses an existing category's spelling
    when it matches ignoring case, so "science" joins "Science"."""
    text = _one_line(category)
    if not text:
        return DEFAULT_CATEGORY
    if len(text) > CATEGORY_MAX_CHARS:
        raise MemoryRequestError(f"The category is over {CATEGORY_MAX_CHARS} characters: use a short name.")
    for known in [*existing, DEFAULT_CATEGORY]:
        if known.lower() == text.lower():
            return known
    return text


# --- files ---------------------------------------------------------------------------

def parse_memory(name: str, text: str) -> Memory:
    """Read a memory file. Tolerates files edited by hand: a missing or partial
    front matter puts the memory under "Other" and uses its first line as the description."""
    category, description, body = "", "", text
    match = _FRONT_MATTER_RE.match(text)
    if match:
        body = text[match.end():]
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            key = key.strip().lower()
            if key == "category":
                category = _one_line(value)
            elif key == "description":
                description = _one_line(value)
    body = body.strip()
    if not description:
        first = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), "")
        description = first[:DESCRIPTION_MAX_CHARS] or "(no description)"
    return Memory(name=name, category=category or DEFAULT_CATEGORY, description=description, body=body)


def format_memory(memory: Memory) -> str:
    return (
        f"---\ncategory: {memory.category}\ndescription: {memory.description}\n---\n\n"
        f"{memory.body.strip()}\n"
    )


def memory_file(memory_dir: Path, name: str) -> Path:
    return memory_dir / f"{name}.md"


def read_memories(memory_dir: Path) -> list[Memory]:
    """Every memory in `memory_dir`, sorted by name (files with invalid names are skipped)."""
    if not memory_dir.is_dir():
        return []
    memories = []
    for path in sorted(memory_dir.glob("*.md")):
        if _NAME_RE.match(path.stem) and path.is_file():
            memories.append(parse_memory(path.stem, path.read_text()))
    return memories


def categories_of(memories: list[Memory]) -> list[str]:
    """Category names in index order: alphabetical, "Other" last."""
    names = {memory.category for memory in memories}
    return sorted(names - {DEFAULT_CATEGORY}, key=str.lower) + (
        [DEFAULT_CATEGORY] if DEFAULT_CATEGORY in names else []
    )


# --- the index -----------------------------------------------------------------------

def _grouped(memories: list[Memory]) -> list[tuple[str, list[Memory]]]:
    by_category: dict[str, list[Memory]] = {}
    for memory in memories:
        by_category.setdefault(memory.category, []).append(memory)
    return [(category, by_category[category]) for category in categories_of(memories)]


def _allocate(sizes: list[int], limit: int) -> list[int]:
    """How many entries of each category to show within `limit`: an equal share
    for each, with what small categories don't use going to the larger ones."""
    shown = [0] * len(sizes)
    remaining = limit
    while remaining > 0:
        open_groups = [i for i, size in enumerate(sizes) if shown[i] < size]
        if not open_groups:
            break
        share = max(1, remaining // len(open_groups))
        for i in open_groups:
            take = min(share, sizes[i] - shown[i], remaining)
            shown[i] += take
            remaining -= take
            if remaining == 0:
                break
    return shown


def format_index(memories: list[Memory], limit: Optional[int] = None) -> str:
    """The index, grouped by category, one line per memory. With `limit`, at most
    that many entries are shown, shared fairly between categories, and a notice
    says what was left out."""
    groups = _grouped(memories)
    sizes = [len(entries) for _, entries in groups]
    shown = _allocate(sizes, limit) if limit is not None else sizes
    lines = []
    left_out = []
    for (category, entries), count in zip(groups, shown):
        lines.append(f"## {category} ({len(entries)})")
        lines.extend(f"- {memory.name}: {memory.description}" for memory in entries[:count])
        if count < len(entries):
            lines.append(f"- … {len(entries) - count} more not shown")
            left_out.append(f"{category}: {len(entries) - count}")
        lines.append("")
    index = "\n".join(lines).strip()
    if left_out:
        hidden = len(memories) - sum(shown)
        index = (
            f"⚠️ Index trimmed: showing {sum(shown)} of {count_memories(len(memories))}; {hidden} left out "
            f"({', '.join(left_out)}). **read_memory_index** returns them all, or one category "
            f"with read_memory_index(category=...).\n\n{index}"
        )
    return index
