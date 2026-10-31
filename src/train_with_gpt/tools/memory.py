"""Coach memory tools: the coach's own undated, editable working knowledge per athlete.

read_memory_index, read_memory, save_memory, update_memory, delete_memory and
build_memory_from_notes (guidance for the one-time backfill from past notes).
Storage and the index format live in ..memory.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import (
    GitSyncError,
    current_user_id,
    git_pull_and_read,
    git_save_file,
    save_error_for_caller,
    save_status_for_caller,
    sync_note_for_caller,
    training_repo_not_configured_message,
    user_scoped_memory_dir,
)
from ..memory import (
    BACKFILL_MEMORY_NAME,
    DESCRIPTION_MAX_CHARS,
    SUGGESTED_CATEGORIES,
    Memory,
    MemoryRequestError,
    categories_of,
    count_memories,
    format_index,
    format_memory,
    memory_file,
    normalize_category,
    normalize_description,
    normalize_name,
    parse_memory,
    read_memories,
)

_SUGGESTED = ", ".join(SUGGESTED_CATEGORIES)
_SILENT = "Carry on with the conversation; there's no need to mention this to the athlete."
_NAME_HELP = "Lowercase words joined by hyphens, e.g. `polarized-base`."
_HOSTED_READ_FAILED = "❌ Error: the notes storage couldn't be read just now. Please try again in a moment."


def _error_for_caller(detail: str) -> str:
    """A read error for the caller: on the hosted server the detail (server
    paths, git output) stays in the log and the user gets a generic line."""
    if current_user_id():
        print(f"[memory] storage error: {detail}", file=sys.stderr)
        return _HOSTED_READ_FAILED
    return f"❌ Error: {detail}"


def _repo_or_error() -> tuple[Optional[Path], Optional[str]]:
    if not config.training_repo_path:
        return None, training_repo_not_configured_message()
    repo_path = Path(config.training_repo_path)
    if not repo_path.exists():
        return None, _error_for_caller(f"Training repository path no longer exists: {repo_path}")
    return repo_path, None


def _text(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def _with_sync_note(pull_output: Optional[str], text: str) -> str:
    # A failed sync can hide memories saved from another device: say so.
    note = sync_note_for_caller(pull_output, current_user_id())
    return f"_{note}_\n\n{text}" if note else text


async def _read_all(repo_path: Path) -> tuple[Optional[str], list[Memory]]:
    memory_dir, _ = user_scoped_memory_dir(repo_path, current_user_id())
    return await asyncio.to_thread(git_pull_and_read, repo_path, lambda: read_memories(memory_dir))


# --- read_memory_index ----------------------------------------------------------------

def read_memory_index_tool() -> Tool:
    return Tool(
        name="read_memory_index",
        description=(
            "Read the index of your coach memory for this athlete: one line per memory "
            "(name: description), grouped by category. Your memory is your own working "
            "knowledge about the athlete (science behind an approach and how it's working, how "
            "to coach them, open threads and hypotheses, data quirks and vocabulary). "
            "start_consultation already includes the index (capped); call this for the full "
            "index, or one category, then read_memory for the full text."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Only this category (case doesn't matter). Leave out for the full index.",
                },
            },
        },
    )


async def read_memory_index_handler(arguments: dict) -> list[TextContent]:
    try:
        repo_path, error = _repo_or_error()
        if error:
            return _text(error)
        pull_output, memories = await _read_all(repo_path)

        if not memories:
            return _text(_with_sync_note(pull_output, (
                "ℹ️ No memories saved yet.\n\n"
                "Save one with **save_memory** whenever you learn something worth keeping about "
                f"this athlete (suggested categories: {_SUGGESTED})."
            )))

        wanted = " ".join(str(arguments.get("category") or "").split())
        if wanted:
            selected = [memory for memory in memories if memory.category.lower() == wanted.lower()]
            if not selected:
                return _text(_with_sync_note(pull_output, (
                    f"ℹ️ No memories in category {wanted!r}. Categories: "
                    + ", ".join(categories_of(memories))
                )))
            header = f"Coach memory, category {selected[0].category}: {len(selected)} of {count_memories(len(memories))}."
        else:
            selected = memories
            groups = len(categories_of(memories))
            header = f"Coach memory: {count_memories(len(memories))} in {groups} {'category' if groups == 1 else 'categories'}."

        text = (
            f"{header} Read full text with **read_memory** (names=[...]).\n\n"
            + format_index(selected)
        )
        return _text(_with_sync_note(pull_output, text))

    except Exception as e:
        print(f"Error reading memory index: {e}", file=sys.stderr)
        return _text(_error_for_caller(str(e)))


# --- read_memory ----------------------------------------------------------------------

def read_memory_tool() -> Tool:
    return Tool(
        name="read_memory",
        description=(
            "Read the full text of one or more of your coach memories by name (the names are "
            "in the memory index: start_consultation or read_memory_index)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of the memories to read, as shown in the index.",
                },
            },
            "required": ["names"],
        },
    )


async def read_memory_handler(arguments: dict) -> list[TextContent]:
    try:
        repo_path, error = _repo_or_error()
        if error:
            return _text(error)
        names = arguments.get("names")
        if isinstance(names, str):
            names = [names]
        names = [name for name in (names or []) if isinstance(name, str) and name.strip()]
        if not names:
            return _text("❌ Error: No memory names provided. read_memory_index lists them.")

        pull_output, memories = await _read_all(repo_path)
        by_name = {memory.name: memory for memory in memories}

        found, missing = [], []
        for name in dict.fromkeys(name.strip().lower() for name in names):
            memory = by_name.get(name)
            if memory:
                found.append(
                    f"# {memory.name}\nCategory: {memory.category}\nDescription: {memory.description}\n\n{memory.body}"
                )
            else:
                missing.append(name)

        parts = found
        if missing:
            parts = parts + [
                "ℹ️ No memory named " + ", ".join(f"`{name}`" for name in missing)
                + ". read_memory_index lists the saved memories."
            ]
        return _text(_with_sync_note(pull_output, "\n\n-----\n\n".join(parts)))

    except Exception as e:
        print(f"Error reading memories: {e}", file=sys.stderr)
        return _text(_error_for_caller(str(e)))


# --- writes ---------------------------------------------------------------------------

async def _write(name: str, update, commit_message: str, done) -> list[TextContent]:
    """Apply `update` (current text -> new text, or None to delete) to the
    memory's file under the repo lock, commit and push. `done` is the success
    line, or a function returning it (called after the save)."""
    repo_path, error = _repo_or_error()
    if error:
        return _text(error)
    user_id = current_user_id()
    memory_dir, relative_dir = user_scoped_memory_dir(repo_path, user_id)
    relative_path = f"{relative_dir}/{name}.md"
    status = await asyncio.to_thread(git_save_file, repo_path, relative_path, update, commit_message)
    status = save_status_for_caller(status, user_id)
    shown_path = relative_path if user_id else memory_file(memory_dir, name)
    done = done() if callable(done) else done
    return _text(f"✅ {done}, committed{status}: {shown_path}\n\n{_SILENT}")


def _write_error(action: str, e: Exception) -> list[TextContent]:
    if isinstance(e, MemoryRequestError):
        return _text(f"❌ The memory was not {action}: {e}")
    if not isinstance(e, GitSyncError):
        print(f"Error: memory not {action}: {e}", file=sys.stderr)
    return _text(f"❌ Error: The memory was not {action}. {save_error_for_caller(str(e), current_user_id())}")


def _existing_categories(repo_path: Path) -> list[str]:
    memory_dir, _ = user_scoped_memory_dir(repo_path, current_user_id())
    return categories_of(read_memories(memory_dir))


def save_memory_tool() -> Tool:
    return Tool(
        name="save_memory",
        description=(
            "Save a new memory: your own working knowledge about this athlete, kept between "
            "chats. It's for you, the coach, not a document for the athlete: save on your own, "
            "mid-conversation, whenever you learn something worth keeping, without asking or "
            "mentioning it, and write candidly. Good memories: the science behind an approach "
            "(sources, and how it's working for this athlete), how to coach them (\"pushes back "
            "on rest days; frame recovery as performance\"), open threads and hypotheses to "
            "check, data quirks and vocabulary. Not for: confirmed conclusions about the "
            "athlete (the profile, save_athlete_profile), health details (they belong in the "
            "profile with the athlete's OK; a memory may only point to it), goals (save_goals), "
            "or one consultation's summary (save_consultation_notes). Refuses a name that "
            "already exists: prefer update_memory on an existing memory over a near-duplicate. "
            "No dates needed; memories are edited in place."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": f"Short unique name. {_NAME_HELP}"},
                "category": {
                    "type": "string",
                    "description": (
                        "The index groups memories by category: reuse an existing one (see the index); "
                        f"start a new one only when nothing fits. Suggested: {_SUGGESTED}. Empty: Other."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": f"One line for the index (at most {DESCRIPTION_MAX_CHARS} characters).",
                },
                "content": {"type": "string", "description": "The memory itself, in Markdown."},
            },
            "required": ["name", "description", "content"],
        },
    )


async def save_memory_handler(arguments: dict) -> list[TextContent]:
    try:
        name = normalize_name(arguments.get("name"))
        description = normalize_description(arguments.get("description"))
        content = str(arguments.get("content") or "").strip()
        if not content:
            raise MemoryRequestError("No content provided.")
        repo_path, error = _repo_or_error()
        if error:
            return _text(error)
        saved = {}

        def create(current: Optional[str]) -> str:
            if current is not None:
                raise MemoryRequestError(
                    f"a memory named `{name}` already exists. Use update_memory to change it "
                    "(read_memory shows its text), or pick another name."
                )
            category = normalize_category(arguments.get("category"), _existing_categories(repo_path))
            saved["category"] = category
            return format_memory(Memory(name=name, category=category, description=description, body=content))

        return await _write(name, create, f"Save memory {name}", lambda: f"Memory `{name}` saved in {saved['category']}")
    except Exception as e:
        return _write_error("saved", e)


def update_memory_tool() -> Tool:
    return Tool(
        name="update_memory",
        description=(
            "Change an existing memory: replace its content, append to it (e.g. new evidence on "
            "whether an approach works), or change its description or category. Like save_memory, "
            "do it on your own as you learn, without asking or mentioning it. Give only the fields "
            "to change; content and append can't be combined."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The memory's name, as in the index."},
                "content": {"type": "string", "description": "New full content, replacing the old."},
                "append": {"type": "string", "description": "Text to add at the end of the content."},
                "description": {
                    "type": "string",
                    "description": f"New one-line description (at most {DESCRIPTION_MAX_CHARS} characters).",
                },
                "category": {
                    "type": "string",
                    "description": "Move the memory to this category (\"Other\" for no category). Leave out to keep it.",
                },
            },
            "required": ["name"],
        },
    )


async def update_memory_handler(arguments: dict) -> list[TextContent]:
    try:
        name = normalize_name(arguments.get("name"))
        content = str(arguments.get("content") or "").strip()
        append = str(arguments.get("append") or "").strip()
        description_arg = arguments.get("description")
        description = normalize_description(description_arg) if _one_line_given(description_arg) else None
        category_arg = arguments.get("category") if _one_line_given(arguments.get("category")) else None
        if content and append:
            raise MemoryRequestError("give either content (replace) or append, not both.")
        if not (content or append or description or category_arg):
            raise MemoryRequestError("nothing to change: give content, append, description or category.")
        repo_path, error = _repo_or_error()
        if error:
            return _text(error)

        def change(current: Optional[str]) -> str:
            if current is None:
                raise MemoryRequestError(
                    f"no memory named `{name}`. read_memory_index lists the saved memories; "
                    "save_memory creates a new one."
                )
            memory = parse_memory(name, current)
            if content:
                memory.body = content
            if append:
                memory.body = f"{memory.body.rstrip()}\n\n{append}".strip()
            if description:
                memory.description = description
            if category_arg:
                memory.category = normalize_category(category_arg, _existing_categories(repo_path))
            return format_memory(memory)

        return await _write(name, change, f"Update memory {name}", f"Memory `{name}` updated")
    except Exception as e:
        return _write_error("updated", e)


def _one_line_given(value) -> bool:
    return bool(" ".join(str(value or "").split()))


def delete_memory_tool() -> Tool:
    return Tool(
        name="delete_memory",
        description=(
            "Delete a memory that's wrong, resolved (e.g. an open thread that's been settled), or "
            "moved to the athlete profile. Also when the athlete asks you to forget something."
        ),
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "The memory's name, as in the index."}},
            "required": ["name"],
        },
    )


async def delete_memory_handler(arguments: dict) -> list[TextContent]:
    try:
        name = normalize_name(arguments.get("name"))

        def remove(current: Optional[str]) -> None:
            if current is None:
                raise MemoryRequestError(f"no memory named `{name}`. read_memory_index lists the saved memories.")
            return None

        return await _write(name, remove, f"Delete memory {name}", f"Memory `{name}` deleted")
    except Exception as e:
        return _write_error("deleted", e)


# --- build_memory_from_notes --------------------------------------------------------------

def build_memory_from_notes_tool() -> Tool:
    return Tool(
        name="build_memory_from_notes",
        description=(
            "Guidance for the one-time backfill of your coach memory from past consultation "
            "notes: read them a month at a time and save what's still useful into memory. Call it "
            "when the athlete agrees to the pass start_consultation offers, when they ask for it, "
            "or to continue a pass that ended partway. Returns instructions only."
        ),
        inputSchema={"type": "object", "properties": {}},
    )


BUILD_MEMORY_GUIDANCE = f"""🧠 Building your coach memory from past notes (one-time backfill)

Past consultation notes hold working knowledge that belongs in your memory: research you
found and how it played out, how this athlete responds to coaching, open threads, data
quirks and their vocabulary. This pass moves it there, one batch at a time, saving after
every batch so nothing is lost if the chat ends.

**Before you start**
1. **read_memory_index** for what's already saved. If there is a `{BACKFILL_MEMORY_NAME}` memory,
   **read_memory** it: it says the date an earlier pass reviewed up to. Continue with the notes
   after that date; if it says the pass was declined, or there is none, start from the
   oldest note.
2. **list_consultation_notes** for the dated index of every note. Work from the oldest
   month to the newest.

**For each batch (a month; a couple of weeks if a month has many notes)**
1. **read_consultation_notes** with since/until covering the batch.
2. Pick out what is still useful for coaching. Skip:
   - what's already in the athlete profile or the goals: **read_goals** once before the
     first batch, and **read_athlete_profile** unless start_consultation included the profile
   - what's no longer true or was settled later (newer notes tell; check with
     **search_consultation_notes** when in doubt)
   - health details: they belong in the profile, with the athlete's OK. A memory may only
     point to it
   - one-off session details and weekly numbers the data tools recompute
3. Save it: **update_memory** (append the new evidence) when a memory on the topic
   exists, rather than a near-duplicate; **save_memory** for new ones, in the right category
   (reuse the index's categories; suggested: {_SUGGESTED}). Write candidly; it's for you.
4. Record progress before the next batch: **save_memory** the first time, then
   **update_memory**, `{BACKFILL_MEMORY_NAME}` in category Other, with the description
   "Notes backfill: reviewed up to YYYY-MM-DD (in progress)", with the batch's last day (the
   `until` date you read up to), so the next batch starts after that date.

**When every month is done:** set the `{BACKFILL_MEMORY_NAME}` description to "Notes backfill:
done, reviewed through YYYY-MM-DD". The athlete asked for this pass, so tell them briefly that
it's done; don't list every memory unless they ask.

**Keep the athlete first:** the pass takes many tool calls. If they want to talk about
training, pause and pick it up later; the progress memory says where to continue, and the
next start_consultation shows it.
"""


async def build_memory_from_notes_handler(arguments: dict) -> list[TextContent]:
    return _text(BUILD_MEMORY_GUIDANCE)
