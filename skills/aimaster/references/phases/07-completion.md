# Completion

Generate the handoff manifest. Report separately: real artifacts, prepared-only jobs, technical QA, visual QA, user approvals, missing capabilities, `outcome_unknown` actions, blockers, and unfinished work. Mark complete only after an assembly outcome or handoff exists, technical QA passed, visual QA is explicitly passed or `not_run` with a reason, every capability is executed/not required or its fallback is accepted, and no blocker is open. Prepared fallbacks remain at `assembly`/`ready_for_handoff`.
