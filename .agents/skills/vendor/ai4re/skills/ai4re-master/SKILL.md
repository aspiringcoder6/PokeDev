---
name: ai4re-master
description: >
  Supervisor for AI-supported requirements engineering per the IREB AI4RE Prompt Guide.
  Use when a requirements-related request is broad, mixes several RE tasks, or does not name
  a specific technique — e.g. "help me with the requirements for X", "turn these interview
  notes into a specification", "review and improve our requirements process", or any request
  spanning elicitation, documentation, validation and management. Classifies the RE task,
  selects and sequences the specialized ai4re skills, plans the workflow, carries shared
  context (glossary, assumptions, open questions) across steps, and quality-checks the
  combined result. For a single, clearly named task, use the specialized skill directly.
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: All (Elicitation, Documentation, Validation, Management)
  ai4re-cluster: All (supervisor)
  ai4re-use-cases: [All 23 use cases via routing]
---

# AI4RE Master Consultant

Orchestrates the nine specialized requirements-engineering skills of this repository:
classifies the request, plans a workflow, routes to the right skills in the right order,
and supervises quality across the whole chain.

## Provenance

`[AI4RE-adapted]` The task taxonomy (4 IREB core activities → 9 clusters → 23 use cases),
the routing targets and all quality rules originate from the IREB AI4RE Prompt Guide. The
orchestration layer itself (routing logic, workflow plans, shared-context management) is
supplementary infrastructure `[Supplementary: this repository]` built on that taxonomy.

## When to use / when not to use

**Use when:**
- The request is broad or fuzzy ("we need requirements for a new fleet management system").
- Several RE tasks are mixed in one request ("clean up this transcript, extract the
  requirements and write user stories").
- The user asks which RE step or technique is appropriate.
- An end-to-end deliverable is requested (specification, backlog, review report).

**Do not use when:**
- The request names exactly one task that maps to one skill — invoke that skill directly
  (see routing table). Orchestration overhead without benefit.
- The request is not requirements engineering (general coding, project management outside
  RE scope) — say so and work without ai4re skills.

## Roles

- **Claude acts as:** senior requirements engineering consultant (IREB CPRE level) and
  workflow planner; adopts the specialized skill's expert role during each step.
- **Typical users:** requirements engineers, business analysts, product owners, project
  leads — including stakeholders who do not know RE terminology.

## Core workflow

1. **Classify.** Map the request to IREB core activities and AI4RE use cases using
   [references/routing.md](references/routing.md). State your classification in one
   sentence so the user can correct it.
2. **Check preconditions.** Each skill has input preconditions (e.g. extraction needs
   cleaned material; impact analysis needs trace links). If missing, add the producing
   skill as an upstream step.
3. **Plan.** Single task → route directly. Multiple tasks → assemble a workflow from
   [references/workflows.md](references/workflows.md) or compose a custom sequence. Present
   the plan briefly (steps, skill per step, expected artifact per step) before executing —
   unless the user already requested exactly this chain.
4. **Clarify once, centrally.** Collect the clarifying questions of all planned steps and
   ask them together up front (domain, system, target formats, quality standard, audience).
   Do not re-ask per step what is already answered.
5. **Execute step by step.** Load each routed skill's SKILL.md and follow it. Pass shared
   context forward between steps (see below). Announce artifact handoffs ("Extraction
   done — 14 candidates; formulating them as user stories next").
6. **Supervise quality.** After the last step, run the cross-skill review from
   [references/checklists.md](references/checklists.md): terminology consistent across all
   artifacts, no contradictions between steps, every requirement traceable to its source.
7. **Deliver.** Consolidated result + consolidated assumptions, open questions and risks
   from all steps + recommended next RE activities. Label everything a draft requiring
   expert validation. `[AI4RE]` (general caution).

## Shared context across steps

Maintain and pass forward through every step:

- **Glossary/synonym table** — terminology decisions bind all later steps.
- **Assumptions log** — every `Assumption:` from any step, deduplicated.
- **Open questions** — accumulate; answered ones are removed with their answer noted.
- **Traceability thread** — each artifact references what it was derived from
  (transcript → candidate → requirement → model/test case).

## Use cases

The 23 AI4RE use cases are served through the nine routed skills — see the full routing
table in [references/routing.md](references/routing.md) and the standard multi-skill
workflows in [references/workflows.md](references/workflows.md). Summary:

| IREB activity | Cluster | Skill |
|---|---|---|
| Elicitation | Explore | `elicitation-preparation` |
| Elicitation | Transcribe | `elicitation-transcription` |
| Elicitation | Extract | `requirements-extraction` |
| Documentation | Formulate | `requirements-writing` |
| Documentation | Translate | `requirements-translation` |
| Validation | Validate | `requirements-validation` |
| Validation | Verify | `requirements-verification` |
| Management | Align | `change-impact-analysis` |
| Management | Assign | `requirements-traceability` |

## Output formats

Whatever the routed skills produce, plus master-level artifacts: workflow plan (numbered
steps + skills + artifacts), consolidated specification document, RE status report
(artifacts, quality findings, open questions, next steps).

## Quality gates

- Right skill for the task (no formulation work inside extraction, etc.).
- Preconditions satisfied before each step ran.
- Terminology, IDs and abstraction levels consistent across all produced artifacts.
- Consolidated assumptions/open-questions section present in the final deliverable.

## Self-review protocol

Before delivering: Was the classification confirmed or at least stated? Did any step
silently skip its own self-review? Are there contradictions *between* step outputs
(e.g. persona vs. stakeholder list, test case vs. acceptance criterion)? Is the
traceability thread unbroken from source material to final artifact?

## References

| Load | When |
|------|------|
| [references/routing.md](references/routing.md) | Classifying any request; picking the target skill |
| [references/workflows.md](references/workflows.md) | Multi-step requests; end-to-end deliverables |
| [references/checklists.md](references/checklists.md) | Final cross-skill quality review |
| [references/templates.md](references/templates.md) | Intake briefing; step handoffs; status report |
| [references/examples.md](references/examples.md) | Showing users how orchestration works |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone consultant prompt for another AI tool |
