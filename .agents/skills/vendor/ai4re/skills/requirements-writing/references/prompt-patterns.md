# Prompt Patterns — Requirements Writing

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates and worked
> examples of the Formulate cluster. Pattern names follow common prompt-engineering
> vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Every template: "AI's role" (specification/domain expert) + "My role" (requirements engineer) | Adopt the expert persona *and* model the requester's perspective; calibrate vocabulary to both |
| **Purpose priming** | "My purpose:" line states the quality goal before the task | Keep the end state (readable, quality-conformant requirement) in view, not just the mechanical task |
| **Stepwise task decomposition** (chain of thought) | Specify Requirement steps 1–4 | Execute numbered steps in order; show which step you are in for transparency |
| **Conditional branching** | Steps 1/2a/2b: behavior depends on whether a standard was detected | Encode explicit if/else in procedures instead of guessing |
| **Interactive clarification** (ask-before-proceed) | Step 2b: stop, suggest alternatives, ask which standard to use | Prefer one targeted question over a wrong default when the choice materially changes output |
| **Self-validation loop** (generate → critique → regenerate) | Step 4: validate against quality standard, request missing info, repeat step 3 | Never deliver the first draft unchecked; iterate until the gate passes or gaps become open questions |
| **Quality-standard anchoring** | `[QUALITY]` variable: INVEST, ISO 29148, INCOSE, IREB CPRE | Name the standard explicitly; validate criterion by criterion, visibly (✔/✘ per criterion, as in the guide's INVEST example) |
| **Output format constraint** | `[FORMAT]` variable; synonym table column spec | Fix format before generating; deviations are defects |
| **Strict grounding** | Synonym table: term may only appear if used in the source document | Separate *extracted* from *suggested*; never invent domain vocabulary |
| **Variable configuration** | All `[SQUARE_BRACKET]` variables | Resolve every variable before executing; unresolved variables are clarifying questions |
| **Assumptions-first framing** | Decompose example opens with "Assumptions & Scope" | State scope and assumptions *before* the deliverable so reviewers see the frame first |
| **Risk callouts + recommendation** | Decompose example ends with "Risks / Points to Clarify" and an MVP recommendation | End deliverables with open risks and a prioritized next step |
| **Draft-not-decision** | Pitfalls: "Treat AI output as a draft, not a decision" | Label output as draft; require human expert validation |
