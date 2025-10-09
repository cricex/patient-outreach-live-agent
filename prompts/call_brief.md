# Example: CALL_BRIEF Format

```
BEGIN CALL_BRIEF

Agent Name: Assistant  
ORG_NAME: Microsoft Health Clinic  

NAME: Charles


AGE: 55                            # Internal; speak only if asked  
AGE_BUCKET_SPOKEN: in your fifties  
SEX: male                          # Internal; helps with pronouns if needed  
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
```

---

## Notes

* Each field should appear exactly as shown.
* Comments (lines beginning with `#`) are optional and for internal use only.
* The `NEEDS` section supports multiple entries if `MULTI_NEED` is `true`.
* The `INTENT_CLUES` and `SCHED_WINDOW_PREF` help guide conversational flow for scheduling.