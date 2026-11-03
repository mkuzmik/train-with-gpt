"""Where a hosted user's activity tools read from: Strava (default) or intervals.icu.

Hosted (OAuth'd) users sign in with Strava, so their activities come from
Strava unless the model asks for intervals.icu with the `source` argument on
get_activities / analyze_activity / analyze_lap. That only works when the user
connected their own intervals.icu key at login (intervals_connect.py). The
stdio/personal paths always read intervals.icu and aren't offered the argument.
"""

from mcp.types import Tool

STRAVA = "strava"
INTERVALS_ICU = "intervals_icu"
SOURCES = (STRAVA, INTERVALS_ICU)
DEFAULT_SOURCE = STRAVA

ACTIVITY_TOOLS = frozenset({"get_activities", "analyze_activity", "analyze_lap"})

SOURCE_PARAM = {
    # Nullable: some clients send null for an optional argument they leave unset.
    "type": ["string", "null"],
    "enum": [*SOURCES, None],
    "default": DEFAULT_SOURCE,
    "description": (
        "Where to read activities from: 'strava' (default, also when omitted or null) or "
        "'intervals_icu' (only if the athlete "
        "connected intervals.icu at login). intervals.icu has precomputed zones and the athlete's "
        "own lap/interval edits, so prefer it when they say they fixed or redefined laps there "
        "(e.g. a mis-pressed lap button), or when Strava's laps don't match the workout. Activity "
        "ids differ between sources, so pass the same source to analyze_activity/analyze_lap that "
        "get_activities used."
    ),
}

INTERVALS_NOT_CONNECTED_MESSAGE = (
    "ℹ️ intervals.icu isn't connected for this athlete, so activities can only come from Strava "
    "(call again without `source`, or with source='strava'). To add intervals.icu, sign in to this "
    "server again (e.g. disconnect and reconnect this connector in Claude's settings) and paste "
    "your intervals.icu API key on the page shown after the Strava login."
)

INTERVALS_NOT_OFFERED_MESSAGE = (
    "ℹ️ This server doesn't offer connecting intervals.icu, so activities can only come from "
    "Strava (call again without `source`, or with source='strava')."
)


def invalid_source_message(source) -> str:
    return f"❌ Error: unknown source {source!r}. Use one of: {', '.join(SOURCES)}."


def with_source_param(tool: Tool) -> Tool:
    """A copy of an activity tool's definition with the hosted-only `source` argument."""
    schema = dict(tool.inputSchema)
    schema["properties"] = {**schema.get("properties", {}), "source": SOURCE_PARAM}
    return tool.model_copy(update={"inputSchema": schema})


def strava_id_error(activity_id) -> str | None:
    """Strava ids are numeric; an intervals.icu-style id (e.g. "i123") means the wrong source."""
    if str(activity_id).isdigit():
        return None
    return (
        f"❌ Error: '{activity_id}' isn't a Strava activity id (Strava ids are numeric). "
        "If it came from intervals.icu, call again with source='intervals_icu'."
    )
