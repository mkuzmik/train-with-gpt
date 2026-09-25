"""Static training-science guidance for the coach.

Kept in its own module so that:
- ``start_consultation`` can append it today, and the assembled consultation
  context (docs/ideas/consultation-context.md) can drop it into its reserved
  slot later without rewording;
- onboarding can import ``SAFETY_RULES`` for its red-flag screening, so there
  is one safety list.

Every source below is from the verified reference list in
docs/ideas/science-based-coaching.md. Never add a citation that is not in that
list; tests/unit/test_coaching_science.py enforces it and the size budget.
"""

# Appended to HRV and resting-HR tool output.
BASELINE_NOTE = (
    "ℹ️ Interpret against the athlete's own baseline and normal range, not "
    "population norms or \"higher/lower = better\". Single nights are noisy; "
    "act on sustained shifts, and ask how they feel."
)

# Size budget for TRAINING_SCIENCE, in characters (about 700 tokens).
TRAINING_SCIENCE_MAX_CHARS = 2800

PRINCIPLES = """\
## Training science (reviewed: 2026-09; confidence in brackets)
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
Safety - pause coaching, recommend a professional, and record it in the notes:
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
