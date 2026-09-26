"""self_test tool and the "self-test" prompt (the checks live in ../self_test.py)."""

from mcp.types import GetPromptResult, Prompt, PromptMessage, TextContent, Tool

from ..helpers import current_user_id
from ..self_test import READ_ONLY_TOOLS, READ_ONLY_TOOLS_NOT_IN_PROMPT, WRITE_TOOLS, format_report, run_self_test

SELF_TEST_PROMPT_NAME = "self-test"


def self_test_tool() -> Tool:
    """Return the self_test tool definition."""
    return Tool(
        name="self_test",
        description=(
            "Health check of this connector, run by the server itself: data source login, "
            "reading activities/wellness (counts only), syncing the training-notes repo, saving "
            "and pushing a small marker file (selftest/<user>.md; it never creates or edits notes "
            "or goals, but the usual repo sync may pull remote changes to them and push commits "
            "already pending in the clone), build info and the list of registered tools. Call it "
            "when the user asks to test, "
            "health-check or verify the connector (e.g. after a deploy). Show the returned table "
            "to the user verbatim, and never claim anything works beyond what the table shows."
        ),
        inputSchema={"type": "object", "properties": {}},
    )


async def self_test_handler(arguments: dict) -> list[TextContent]:
    """Handle self_test tool calls: run the checks for the calling user."""
    report = await run_self_test(current_user_id())
    return [TextContent(type="text", text=format_report(report))]


def self_test_prompt() -> Prompt:
    return Prompt(
        name=SELF_TEST_PROMPT_NAME,
        description=(
            "Test the connector end to end: run self_test, then call each read-only tool once "
            "and report which tools this client couldn't find. Never calls a tool that changes "
            "notes, goals or configuration (self_test itself only saves its marker file)."
        ),
    )


def self_test_prompt_result() -> GetPromptResult:
    calls = "\n".join(f"   - `{name}` with {args}" for name, args in READ_ONLY_TOOLS.items())
    text = f"""Run a health check of the Train with GPT connector.

1. Call `self_test` and show its table to me verbatim.
2. Then call each of these read-only tools once, with minimal arguments:
{calls}
   For each, report only OK or the error message, in one short table. Do not
   summarize, analyze or comment on the data they return.
3. Do NOT call any other tool. In particular never call {", ".join(f"`{t}`" for t in WRITE_TOOLS if t != "self_test")}:
   they change my real notes, goals or configuration. `{"`, `".join(READ_ONLY_TOOLS_NOT_IN_PROMPT)}` are skipped on purpose.
4. Finish with the list of tools above that you could not find in this client
   (not loaded or not available), or "all tools found".
Never claim anything works beyond what the results show."""
    return GetPromptResult(
        description="Connector health check",
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )
