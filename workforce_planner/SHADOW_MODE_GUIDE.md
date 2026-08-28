# Selective Hybrid RL Shadow-Mode Guide

The model must remain advisory after simulation approval.

Use `data/dynamic_shadow_template.csv` to record:

- Planning date and decision round.
- Employee alias, availability and current field.
- Budgeted-greedy proposal.
- RL accept/veto recommendation.
- Safety-shield or fallback decision.
- Supervisor decision and reason.
- Predicted, conservative and actual remaining-shift kilograms.
- Field crop remaining before and after the decision.
- Transfer time, weather and operational disruption.

Compare the approved hybrid model against budgeted dynamic greedy using actual:

- Total fulfilled crop.
- Bottom-quartile field coverage.
- Number of critical fields.
- Reassignments and transfer time.
- Supervisor override rate.
- Employee movement burden.

Do not set `shadow_mode_approved` to true until a controlled review shows measurable operational benefit, zero hard-rule violations and acceptable workforce movement.
