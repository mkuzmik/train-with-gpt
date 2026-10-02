"""Static training-science guidance for the coach.

Kept in its own module so that the consultation guidance and any other
guidance that needs it (e.g. a red-flag check during onboarding) share one
text, and so its size budget and sources can be tested on their own.

Every DOI cited here must be in SOURCES, and every SOURCES entry comes from
the verified reference list in the design (GitHub issue #33: each DOI was
resolved on Crossref and checked against its abstract). Never add a citation
from memory; tests/unit/test_coaching_science.py enforces the list and the
size budget.
"""

# Appended to HRV and resting-HR tool output.
BASELINE_NOTE = (
    "ℹ️ Interpret against the athlete's own baseline and normal range, not "
    "population norms or \"higher/lower = better\". Single nights are noisy; "
    "act on sustained shifts, and ask how they feel."
)

# Size budget for TRAINING_SCIENCE, in characters (about 700 tokens).
TRAINING_SCIENCE_MAX_CHARS = 2800

# The only sources TRAINING_SCIENCE may cite: DOI -> short reference.
SOURCES = {
    "10.1007/s40279-024-02149-3": "Rosenblat 2025, Sports Med (intensity distribution, IPD network meta-analysis)",
    "10.1136/bjsports-2024-109380": "Frandsen 2025, Br J Sports Med (single-run distance spikes, cohort)",
    "10.1123/ijspp.2019-0864": "Impellizzeri 2020, IJSPP (ACWR pitfalls)",
    "10.1371/journal.pone.0282838": "Wang 2023, PLoS One (taper meta-analysis)",
    "10.1007/s40279-023-01978-y": "Llanos-Lagos 2024, Sports Med (strength training, running economy)",
    "10.1007/s40279-024-02018-z": "Llanos-Lagos 2024, Sports Med (strength training, running performance)",
    "10.1007/s00421-025-05883-2": "Llanos-Lagos 2025, Eur J Appl Physiol (heavy strength training, cyclists)",
    "10.1016/j.jand.2015.12.006": "Thomas 2016, J Acad Nutr Diet (AND/DC/ACSM nutrition position)",
    "10.1016/j.tjnut.2026.101442": "Morton 2026, J Nutr (carbohydrate during exercise)",
    "10.3390/ijerph181910299": "Manresa-Rocamora 2021, IJERPH (HRV-guided training meta-analysis)",
    "10.1136/bjsports-2020-102025": "Walsh 2021, Br J Sports Med (sleep expert consensus)",
    "10.1007/s40279-020-01319-3": "McNulty 2020, Sports Med (menstrual cycle phase meta-analysis)",
    "10.1136/bjsports-2023-106994": "Mountjoy 2023, Br J Sports Med (IOC REDs consensus)",
    "10.1123/ijsnem.21.2.97": "Garthe 2011, IJSNEM (weight-loss rate in athletes, RCT)",
}

PRINCIPLES = """\
## Training science (both paths; reviewed: 2026-09; confidence in brackets)
Use these when advising. Cite only the sources named here or records a tool
returned; never cite from memory. If unsure, say so.
- Intensity: most volume easy. Pyramidal and polarized both work; no model is
  clearly best. [moderate; "which model" contested] (doi:10.1007/s40279-024-02149-3)
- Progression (running): avoid single runs >10% longer than the longest run
  of the last 30 days; linked to more overuse injury. [emerging, 1 cohort]
  (doi:10.1136/bjsports-2024-109380)
- ACWR "sweet spot" 0.8-1.3 is not established; don't use it as a rule.
  [contested] (doi:10.1123/ijspp.2019-0864)
- Taper: cut volume ~40-60% over <=2-3 weeks, keep intensity. [moderate]
  (doi:10.1371/journal.pone.0282838)
- Strength: heavy (>=80% 1RM) lifting improves running economy [moderate] and
  performance [low-moderate] in runners, and performance in cyclists [low].
  (doi:10.1007/s40279-023-01978-y; doi:10.1007/s40279-024-02018-z;
  doi:10.1007/s00421-025-05883-2)
- Fueling >2.5 h: up to 90 g/h carbohydrate (glucose+fructose) [consensus];
  90-120 g/h for trained, gut-trained athletes [emerging]; >120 g/h
  unsupported. (doi:10.1016/j.jand.2015.12.006; doi:10.1016/j.tjnut.2026.101442)
- HRV/RHR: compare to the athlete's own baseline and normal range, never a
  single night. HRV-guided training is reasonable but not clearly better for
  performance. [low-moderate] (doi:10.3390/ijerph181910299)
- Sleep: short or poor sleep is common; treat it as part of load. Needs vary
  by person. [consensus] (doi:10.1136/bjsports-2020-102025)
- Menstrual cycle: average phase effects are trivial; personalize, don't
  prescribe by phase. [low] (doi:10.1007/s40279-020-01319-3)
Advice format: what, why, confidence, source. Present emerging or contested
items as options, not rules.
"""

SAFETY_RULES = """\
Safety - pause coaching and recommend a professional:
- chest pain, fainting, palpitations or unusual breathlessness in exercise
  -> stop, see a physician;
- signs of low energy availability (missed/changed periods, repeated bone
  stress injuries, frequent illness, persistent fatigue, falling performance)
  -> sports medicine screening (IOC REDs, doi:10.1136/bjsports-2023-106994);
- localized bone pain that worsens with loading -> stop running, get it
  checked;
- fever or systemic illness -> no hard training;
- eating-disorder cues, pregnancy, new medication -> professional advice.
Weight: ask the REDs screening questions first. Only if they are clear: no
crash diets; at most ~0.5-1% body mass/week [emerging]
(doi:10.1123/ijsnem.21.2.97), in low-priority phases, never at the cost of
fueling training. Under 18 or a positive screen: no weight or
body-composition targets; refer instead.
"""

TRAINING_SCIENCE = PRINCIPLES + SAFETY_RULES
