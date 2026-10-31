"""Unit tests for the coach memory tools (read_memory_index, read_memory,
save_memory, update_memory, delete_memory, build_memory_from_notes) and the
index format.

Reads and writes run against a real git clone of a local bare remote. All
memory content here is made up.
"""

import asyncio

from tests.support import (
    as_oauth_user,
    assert_clean_and_in_sync,
    git,
    push_files,
    race_on_commit,
    race_runs,
    referenced_tool_names,
    remote_file,
    remote_files,
    text_of,
)
from train_with_gpt.config import config
from train_with_gpt.memory import DESCRIPTION_MAX_CHARS, Memory, format_index, format_memory, parse_memory
from train_with_gpt.server import list_tools
from train_with_gpt.tools import (
    build_memory_from_notes_handler,
    delete_memory_handler,
    read_memory_handler,
    read_memory_index_handler,
    save_memory_handler,
    update_memory_handler,
)


async def _save(name="polarized-base", category="Science",
                description="Polarized base block, sources and how it's working",
                content="Sources: a synthetic review. Working so far: easy pace improving.") -> str:
    return text_of(await save_memory_handler(
        {"name": name, "category": category, "description": description, "content": content}
    ))


async def _update(**arguments) -> str:
    return text_of(await update_memory_handler(arguments))


async def _index(**arguments) -> str:
    return text_of(await read_memory_index_handler(arguments))


async def _read(*names) -> str:
    return text_of(await read_memory_handler({"names": list(names)}))


async def _delete(name) -> str:
    return text_of(await delete_memory_handler({"name": name}))


# --- save -------------------------------------------------------------------------------

async def test_save_writes_one_file_per_memory_and_pushes_it(training_repo, git_remote):
    output = await _save()

    assert output.startswith("✅ Memory `polarized-base` saved in Science, committed and pushed to remote:")
    assert "no need to mention this to the athlete" in output
    content = remote_file(git_remote, "memory/polarized-base.md")
    assert content == (training_repo / "memory" / "polarized-base.md").read_text()
    assert content.startswith(
        "---\ncategory: Science\ndescription: Polarized base block, sources and how it's working\n---\n\n"
    )
    assert "easy pace improving" in content
    assert "Save memory polarized-base" in git(git_remote, "log", "--format=%s", "main")


async def test_save_refuses_an_existing_name_and_keeps_the_old_memory(training_repo, git_remote):
    await _save(content="Original text")

    output = await _save(content="Replacement text")

    assert output.startswith("❌ The memory was not saved: a memory named `polarized-base` already exists")
    assert "update_memory" in output
    assert "Original text" in remote_file(git_remote, "memory/polarized-base.md")
    assert_clean_and_in_sync(training_repo)


async def test_save_refuses_a_name_another_device_saved_meanwhile(training_repo, git_remote):
    # Another device saves the same name between our commit and our push: the
    # retry sees it, so the existence check holds under concurrency.
    race_on_commit(training_repo, git_remote, {
        "memory/polarized-base.md": "---\ncategory: Science\ndescription: From the phone\n---\n\nPhone text\n",
    })

    output = await _save()

    assert race_runs(training_repo) == 1
    assert "already exists" in output
    assert "Phone text" in remote_file(git_remote, "memory/polarized-base.md")
    assert_clean_and_in_sync(training_repo)


async def test_names_are_lowercased_and_invalid_ones_refused_with_a_suggestion(training_repo, git_remote):
    assert "saved" in await _save(name="Tuesday-Club")
    assert "memory/tuesday-club.md" in remote_files(git_remote)

    output = await _save(name="HR drift / long runs")

    assert output.startswith("❌ The memory was not saved: Invalid memory name")
    assert "`hr-drift-long-runs`" in output
    assert not any("drift" in path for path in remote_files(git_remote))


async def test_a_path_in_the_name_is_refused(training_repo, git_remote):
    output = await _save(name="../goals")

    assert "Invalid memory name" in output
    assert "goals.md" not in remote_files(git_remote)


async def test_description_is_one_line_and_length_limited(training_repo, git_remote):
    await _save(name="vocab", description="'Tuesday club'\nmeans 6x1k at threshold")
    assert "description: 'Tuesday club' means 6x1k at threshold\n" in remote_file(git_remote, "memory/vocab.md")

    output = await _save(name="long", description="x" * (DESCRIPTION_MAX_CHARS + 1))

    assert "not saved" in output and f"over the {DESCRIPTION_MAX_CHARS} limit" in output
    assert "memory/long.md" not in remote_files(git_remote)


async def test_save_requires_description_and_content(training_repo):
    assert "No description provided" in await _save(description=" ")
    assert "No content provided" in await _save(content="")


async def test_categories_are_reused_ignoring_case_and_empty_means_other(training_repo, git_remote):
    await _save(name="a", category="Open threads")
    await _save(name="b", category="open THREADS")
    await _save(name="c", category="")

    assert "category: Open threads\n" in remote_file(git_remote, "memory/b.md")
    assert "category: Other\n" in remote_file(git_remote, "memory/c.md")


# --- read -------------------------------------------------------------------------------

async def test_index_is_grouped_by_category_with_other_last(training_repo):
    await _save(name="zone-model", category="Science", description="Three-zone model")
    await _save(name="misc", category="", description="Something else")
    await _save(name="rest-days", category="Coaching approach", description="Pushes back on rest days")
    await _save(name="polarized-base", category="Science", description="Polarized base")

    output = await _index()

    assert output.startswith("Coach memory: 4 memories in 3 categories.")
    body = output.split("\n\n", 1)[1]
    assert body.index("## Coaching approach (1)") < body.index("## Science (2)") < body.index("## Other (1)")
    assert "- polarized-base: Polarized base\n- zone-model: Three-zone model" in body


async def test_index_for_one_category(training_repo):
    await _save(name="a", category="Science", description="Science memory")
    await _save(name="b", category="Open threads", description="Thread memory")

    output = await _index(category="science")

    assert "category Science: 1 of 2 memories" in output
    assert "Science memory" in output and "Thread memory" not in output
    assert "No memories in category 'Data'" in await _index(category="Data")
    assert "Categories: Open threads, Science" in await _index(category="Data")


async def test_index_when_empty(training_repo):
    output = await _index()

    assert "No memories saved yet" in output
    assert "save_memory" in output


async def test_read_returns_full_text_and_reports_missing_names(training_repo):
    await _save(name="a", content="Body A")
    await _save(name="b", content="Body B", category="Open threads", description="Thread B")

    output = await _read("a", "B", "nope")

    assert "# a\nCategory: Science" in output and "Body A" in output
    assert "# b\nCategory: Open threads\nDescription: Thread B\n\nBody B" in output
    assert "No memory named `nope`" in output


async def test_read_requires_names(training_repo):
    assert "No memory names provided" in text_of(await read_memory_handler({}))


async def test_read_pulls_memories_saved_on_another_device(training_repo, git_remote):
    push_files(git_remote, {"memory/from-phone.md": "---\ncategory: Science\ndescription: Saved on the phone\n---\n\nx\n"})

    assert "from-phone: Saved on the phone" in await _index()


async def test_a_hand_edited_file_without_front_matter_is_still_indexed(training_repo, git_remote):
    push_files(git_remote, {"memory/hand-edit.md": "# Fueling on long runs\n\nTry 60 g carbs per hour.\n"})

    output = await _index()

    assert "## Other (1)\n- hand-edit: Fueling on long runs" in output
    assert "Try 60 g carbs per hour." in await _read("hand-edit")


# --- update -----------------------------------------------------------------------------

async def test_update_replaces_or_appends_to_the_content(training_repo, git_remote):
    await _save(content="First evidence")

    assert "updated" in await _update(name="polarized-base", append="Second evidence")
    assert "First evidence\n\nSecond evidence\n" in remote_file(git_remote, "memory/polarized-base.md")

    await _update(name="polarized-base", content="Rewritten")
    content = remote_file(git_remote, "memory/polarized-base.md")
    assert "Rewritten" in content and "First evidence" not in content
    assert "description: Polarized base block" in content  # untouched


async def test_update_changes_description_and_moves_category(training_repo, git_remote):
    await _save(name="moved", category="Science")
    await _save(name="other", category="Open threads")

    await _update(name="moved", description="New summary", category="open threads")

    content = remote_file(git_remote, "memory/moved.md")
    assert "category: Open threads\ndescription: New summary\n" in content
    assert "## Open threads (2)" in await _index()


async def test_append_racing_another_device_keeps_both(training_repo, git_remote):
    await _save(content="Base text")
    race_on_commit(training_repo, git_remote, {
        "memory/polarized-base.md": "---\ncategory: Science\ndescription: d\n---\n\nBase text\n\nFrom the phone\n",
    })

    output = await _update(name="polarized-base", append="From the desktop")

    assert race_runs(training_repo) == 1
    assert "pushed to remote" in output
    content = remote_file(git_remote, "memory/polarized-base.md")
    assert "From the phone" in content and "From the desktop" in content
    assert_clean_and_in_sync(training_repo)


async def test_update_errors(training_repo):
    await _save()

    assert "either content (replace) or append, not both" in await _update(name="polarized-base", content="a", append="b")
    assert "nothing to change" in await _update(name="polarized-base")
    assert "no memory named `missing`" in await _update(name="missing", append="x")


# --- delete -----------------------------------------------------------------------------

async def test_delete_removes_the_memory_from_the_remote(training_repo, git_remote):
    await _save()

    output = await _delete("polarized-base")

    assert output.startswith("✅ Memory `polarized-base` deleted, committed and pushed to remote")
    assert "memory/polarized-base.md" not in remote_files(git_remote)
    assert "Delete memory polarized-base" in git(git_remote, "log", "--format=%s", "main")
    assert "No memories saved yet" in await _index()
    assert_clean_and_in_sync(training_repo)


async def test_delete_of_a_missing_memory_says_so(training_repo):
    assert "not deleted: no memory named `ghost`" in await _delete("ghost")


# --- storage not available ------------------------------------------------------------

async def test_tools_without_repo_configured():
    for output in (await _save(), await _index(), await _read("a"), await _update(name="a", append="x"),
                   await _delete("a")):
        assert "Training repository not configured" in output


async def test_hosted_user_without_repo_is_pointed_to_the_operator():
    with as_oauth_user("1005"):
        for output in (await _save(), await _index()):
            assert "contact the server's operator" in output


async def test_read_when_repo_path_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "training_repo_path", str(tmp_path / "deleted"))
    assert "path no longer exists" in await _index()


# --- per user ---------------------------------------------------------------------------

async def test_memories_are_per_oauth_user(training_repo, git_remote):
    with as_oauth_user("1001"):
        output = await _save(name="alice-thread", description="Alice's open thread")
    with as_oauth_user("1002"):
        await _save(name="bob-thread", description="Bob's open thread")

    assert "committed and pushed to remote: memory/1001/alice-thread.md" in output
    assert str(training_repo) not in output
    files = remote_files(git_remote)
    assert "memory/1001/alice-thread.md" in files and "memory/1002/bob-thread.md" in files

    with as_oauth_user("1001"):
        alice = await _index()
        alice_read = await _read("bob-thread")
    personal = await _index()

    assert "alice-thread" in alice and "bob-thread" not in alice
    assert "No memory named `bob-thread`" in alice_read
    assert "No memories saved yet" in personal


async def test_hosted_index_does_not_list_other_users_files_pulled_by_the_sync(training_repo, git_remote):
    with as_oauth_user("1001"):
        await _save()
    push_files(git_remote, {"memory/2002/theirs.md": "---\ncategory: Science\ndescription: d\n---\n\nx\n"})

    with as_oauth_user("1001"):
        output = await _index()

    assert "2002" not in output and "Pulled updates" not in output


async def test_concurrent_saves_of_different_memories_both_land(training_repo, git_remote):
    results = await asyncio.gather(_save(name="one"), _save(name="two"))

    assert all("pushed to remote" in result for result in results)
    files = remote_files(git_remote)
    assert "memory/one.md" in files and "memory/two.md" in files
    assert_clean_and_in_sync(training_repo)


# --- the index format -------------------------------------------------------------------

def _memories(category: str, count: int) -> list[Memory]:
    return [Memory(name=f"{category.lower()}-{i:03d}", category=category, description=f"d{i}", body="")
            for i in range(count)]


def test_untrimmed_index_has_no_notice():
    index = format_index(_memories("Science", 3), limit=100)

    assert "trimmed" not in index and "more not shown" not in index
    assert index.count("\n- ") == 3


def test_trimmed_index_shares_the_limit_between_categories_and_says_what_was_left_out():
    memories = _memories("Science", 150) + _memories("Open threads", 10) + _memories("Other", 5)

    index = format_index(memories, limit=100)

    assert index.startswith("⚠️ Index trimmed: showing 100 of 165 memories; 65 left out (Science: 65).")
    assert "read_memory_index" in index
    assert "## Science (150)" in index and "- … 65 more not shown" in index
    entries = [line for line in index.splitlines() if line.startswith("- ") and "more not shown" not in line]
    assert len(entries) == 100
    assert sum(line.startswith("- open threads-") for line in entries) == 10
    assert sum(line.startswith("- other-") for line in entries) == 5


def test_trimming_reports_every_trimmed_category():
    index = format_index(_memories("Science", 80) + _memories("Open threads", 80), limit=100)

    assert "showing 100 of 160 memories; 60 left out (Open threads: 30, Science: 30)" in index


def test_parse_round_trips_a_formatted_memory():
    memory = Memory(name="x", category="Data and vocabulary", description="Tuesday club", body="6x1k\n\n---\n\nmore")

    assert parse_memory("x", format_memory(memory)) == memory


# --- build guidance ---------------------------------------------------------------------

async def test_build_guidance_works_in_batches_and_keeps_progress():
    output = text_of(await build_memory_from_notes_handler({}))

    assert "a month" in output
    assert "`notes-backfill`" in output
    assert "reviewed up to YYYY-MM-DD (in progress)" in output
    assert "already in the athlete profile or the goals" in output
    assert "no longer true" in output
    assert "health details" in output.lower()


async def test_build_guidance_only_uses_existing_tools():
    registered = {tool.name for tool in await list_tools()}
    referenced = referenced_tool_names(text_of(await build_memory_from_notes_handler({})))

    assert {"read_consultation_notes", "save_memory", "update_memory", "read_memory_index"} <= referenced
    assert referenced <= registered, referenced - registered


async def test_counts_read_naturally(training_repo):
    await _save()

    assert (await _index()).startswith("Coach memory: 1 memory in 1 category.")


async def test_save_without_a_category_is_allowed_by_the_schema_and_goes_under_other(training_repo, git_remote):
    from train_with_gpt.tools import save_memory_tool

    assert "category" not in save_memory_tool().inputSchema["required"]
    output = text_of(await save_memory_handler({"name": "loose", "description": "d", "content": "c"}))

    assert "saved in Other" in output


async def test_build_guidance_tracks_progress_by_exact_date_and_reads_the_goals():
    output = text_of(await build_memory_from_notes_handler({}))

    assert "reviewed up to YYYY-MM-DD (in progress)" in output
    assert "after that date" in output
    assert "**read_goals**" in output
    assert "start_consultation showed them" not in output
