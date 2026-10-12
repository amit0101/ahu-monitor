# 🚀 Start Prompt — Aqueduct PdM POC

> Copy and paste this entire prompt into a new chat session to resume work.
> The agent will orient itself and continue from exactly where we left off.

---

## Paste This Into New Chat

```
I'm building a Predictive Maintenance POC for a job application to Milvian Group / Aqueduct.
All implementation phases are COMPLETE. The project is now in testing, polish, and
submission-prep mode. Please read the following files in this order before doing anything else:

1. /Users/amit/aqueduct-assignment/SESSION_HANDOFF.md  ← start here (shows current state)
2. /Users/amit/aqueduct-assignment/DEV_TRACKER.md       ← full task checklist
3. /Users/amit/aqueduct-assignment/aqueduct_predictive_maintenance_plan.md  ← full plan

Once you've read all three, summarise the current state and remaining optional polish items
from SESSION_HANDOFF.md, then ask what I'd like to work on. Do NOT re-implement anything
already marked ✅ unless I explicitly ask.

Useful context:
- Servers: `cd backend && python3 -m uvicorn main:app --reload --port 8000`
          `cd frontend && npm run dev`
- E2E test: `python3 e2e_test.py` (Playwright-Python, headless Chromium; last 11/11 PASS in
  Session 7, but predates Session 8 UI changes and may need updating)
- Type-check frontend after edits: `cd frontend && npx tsc --noEmit` (empty = OK)
- Backend python is `python3` (no `python`). App auto-starts at sim day 25.
- Key constraint: emphasis on "credible predictive-maintenance approach and engineering
  thinking" over production polish — keep that in mind when making tradeoffs.
- UI preferences: clean professional monitoring look, no emojis (use SVG icons), theme via
  CSS vars (`var(--color-*)`, light default), instant/optimistic controls, concise replies.
```

---

## Notes

- Do **not** start the prompt with anything other than the above block — it gives the agent everything it needs
- If the agent asks questions already answered in the docs, redirect it back to `SESSION_HANDOFF.md`
- Update `SESSION_HANDOFF.md` and `DEV_TRACKER.md` at the END of each session before closing
