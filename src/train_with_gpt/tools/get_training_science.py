"""Get training science tool: guidance only, no data is read or written here."""

from mcp.types import Tool, TextContent


def get_training_science_tool() -> Tool:
    """Return the get_training_science tool definition."""
    return Tool(
        name="get_training_science",
        description=(
            "How to base coaching advice on sport science: how to find and check research on "
            "the web, how to present it with a confidence level, when to refer the athlete to a "
            "professional, and a list of reviewed papers to start from. Call it before advising "
            "on training methods, load and progression, tapering, strength, fueling, recovery, "
            "sleep, injury, weight or health. Returns instructions only."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


# Starting points only: every DOI was resolved on Crossref and checked against its
# abstract on 2026-09-25 (see GitHub issue #33). The model is told to look further.
_STARTING_POINTS = [
    ("Intensity distribution", "Rosenblat et al. 2025, Sports Med (IPD network meta-analysis)", "10.1007/s40279-024-02149-3"),
    ("Long-run spikes (running)", "Frandsen et al. 2025, Br J Sports Med (5,200-runner cohort)", "10.1136/bjsports-2024-109380"),
    ("Acute:chronic workload ratio", "Impellizzeri et al. 2020, IJSPP", "10.1123/ijspp.2019-0864"),
    ("Tapering", "Wang et al. 2023, PLoS One (meta-analysis)", "10.1371/journal.pone.0282838"),
    ("Strength, runners' economy", "Llanos-Lagos et al. 2024, Sports Med (meta-analysis)", "10.1007/s40279-023-01978-y"),
    ("Strength, runners' performance", "Llanos-Lagos et al. 2024, Sports Med (meta-analysis)", "10.1007/s40279-024-02018-z"),
    ("Strength, cyclists", "Llanos-Lagos et al. 2025, Eur J Appl Physiol (meta-analysis)", "10.1007/s00421-025-05883-2"),
    ("Nutrition position stand", "Thomas et al. 2016, J Acad Nutr Diet (AND/DC/ACSM)", "10.1016/j.jand.2015.12.006"),
    ("Carbohydrate during exercise", "Morton et al. 2026, J Nutr (review)", "10.1016/j.tjnut.2026.101442"),
    ("Energy availability (REDs)", "Mountjoy et al. 2023, Br J Sports Med (IOC consensus)", "10.1136/bjsports-2023-106994"),
    ("Weight-loss rate", "Garthe et al. 2011, IJSNEM (RCT)", "10.1123/ijsnem.21.2.97"),
    ("HRV-guided training", "Manresa-Rocamora et al. 2021, IJERPH (meta-analysis)", "10.3390/ijerph181910299"),
    ("Sleep", "Walsh et al. 2021, Br J Sports Med (expert consensus)", "10.1136/bjsports-2020-102025"),
    ("Overtraining", "Meeusen et al. 2013, Eur J Sport Sci (ECSS/ACSM consensus)", "10.1080/17461391.2012.730061"),
    ("Menstrual cycle", "McNulty et al. 2020, Sports Med (meta-analysis)", "10.1007/s40279-020-01319-3"),
    ("Sports cardiology", "Pelliccia et al. 2021, Eur Heart J (ESC guideline)", "10.1093/eurheartj/ehaa605"),
]

_STARTING_POINTS_TEXT = "\n".join(
    f"- {topic}: {reference}, https://doi.org/{doi}" for topic, reference, doi in _STARTING_POINTS
)

TRAINING_SCIENCE_GUIDANCE = f"""🔬 Training Science: basing advice on evidence

Ground advice on training, recovery, fueling and health in sport science, and research
it yourself rather than relying on memory.

## Finding evidence
- Search the web for current research: PubMed, Europe PMC, Google Scholar, the Cochrane
  Library, and position stands (ACSM, IOC, ISSN, ECSS, national sports-medicine bodies).
- Weigh it by type: consensus statements and guidelines, then systematic reviews and
  meta-analyses, then single trials, then observational studies. Prefer recent work,
  populations like the athlete (trained or recreational, sport, age, sex) and performance
  or injury outcomes. A newer study doesn't automatically win.
- Check every source before citing it: open it (DOI or PubMed page) and base the claim on
  what it says. Never cite a paper you haven't found in this conversation; models invent
  references.
- The papers below are a starting point, not a limit: look for newer or more specific work.

## Presenting advice
- Say what, why, how sure (consensus / moderate / low / emerging / contested) and the
  source (authors, year, link).
- Give emerging or contested findings as options, not rules, and say when good sources
  disagree.
- The athlete's own data and history come first; population findings are a starting
  assumption. Read HRV and resting HR against their own baseline, not single nights.
- If the evidence is thin, conflicting or you couldn't check it, say so, and suggest how
  the athlete could go deeper: a specific review to read, or a coach, dietitian or
  sports-medicine professional.

## Safety: pause coaching and refer
- Chest pain or pressure, fainting, severe or unusual breathlessness, or palpitations with
  any of these, during or after exercise: stop. If it is happening now, is severe or
  doesn't settle with rest, tell them to call emergency services; otherwise to see a
  physician before training again.
- Signs of low energy availability (missed or changed periods, repeated bone stress
  injuries, frequent illness, persistent fatigue, falling performance): sports-medicine
  screening.
- Localized bone pain that worsens with loading: stop running, get it checked.
- Fever, or illness with symptoms below the neck (chest, aching muscles, stomach):
  no training until it has resolved, then build back gradually.
- Eating-disorder cues, pregnancy, new medication: professional advice.
- Weight: screen for low energy availability first; no crash diets, never at the cost of
  fueling training, and no weight or body-composition targets for under-18s.

## Starting points (checked 2026-09)
{_STARTING_POINTS_TEXT}
"""


async def get_training_science_handler(arguments: dict) -> list[TextContent]:
    """Handle get_training_science tool calls."""
    return [TextContent(type="text", text=TRAINING_SCIENCE_GUIDANCE)]
