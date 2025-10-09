BEGIN CALL_BRIEF
Agent Name: Assistant
ORG_NAME: Microsoft Health Clinic
NAME: Tama
NAME_PRONUNCIATION: TAM-uh        # optional; for TTS only
AGE: 55                            # internal; speak only if asked
AGE_BUCKET_SPOKEN: in your fifties
SEX: male                          # internal; helps with pronouns if needed
PRONOUNS: he/him

MULTI_NEED: false

NEEDS:
- AREA: colonoscopy
  PRIORITY: urgent
  TIMING: now
  WHY_SHORT: Overdue for screening with a family history of colon cancer.
  HISTORY_SPOKEN: Advised to schedule in February 2025; referral placed in February 2021.

INTENT_CLUES: schedule|set up|book|dates|times
SCHED_WINDOW_PREF: this week or next two weeks
END CALL_BRIEF