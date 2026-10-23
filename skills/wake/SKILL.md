---
name: wake
description: End an /l3east:sleep run early because the user is back. Use only when the user types /l3east:wake (press Esc first if Claude is mid-turn).
disable-model-invocation: true
---

# Wake

The user is back, and the sleep hook has already closed the run. Stop the sleep work at a safe point: finish or back out of the current step, start nothing new. Delete crons or loops the run created and stop background shells it started. Then write the morning report the sleep skill describes, for what was done so far, and wait for the user.
