# Prompt Patterns — AI4RE Master Consultant

> **Provenance:** `[Supplementary: this repository]` — orchestration-level patterns; the
> per-use-case patterns live in the specialized skills' `prompt-patterns.md`.

| Pattern | Where the master uses it | How to apply |
|---------|--------------------------|--------------|
| **Task classification** (intent routing) | Workflow step 1 | Map request → taxonomy before doing anything; state the mapping so it can be corrected |
| **Plan-then-execute** | Step 3 | Present the numbered plan before running multi-step work; the plan is itself reviewable output |
| **Multi-agent / skill chaining** | Steps 2, 5 | Treat each specialized skill as an expert agent; the master supplies inputs, collects outputs |
| **Precondition gating** | Step 2 | Insert producing steps instead of running a skill on inadequate input |
| **Centralized clarification** | Step 4 | Batch all steps' questions into one round — avoids question fatigue and mid-chain stalls |
| **Context carryover** | Shared-context section | Glossary, assumptions, open questions and trace thread are explicit artifacts passed between steps, not implicit memory |
| **Supervisor critique** (review-of-reviews) | Step 6 | A final cross-artifact check distinct from each skill's own self-review |
| **Scope honesty** | Routing disambiguation rules | Name what AI4RE does not cover instead of improvising silently |
| **Draft-not-decision** `[AI4RE]` | Step 7 | The consolidated deliverable is a draft; expert validation is required |
