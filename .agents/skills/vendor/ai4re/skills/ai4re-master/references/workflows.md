# Standard Workflows — AI4RE Master Consultant

> **Provenance:** `[Supplementary: this repository]` — workflow compositions built from
> AI4RE use cases; each step executes the referenced skill's `[AI4RE]` procedure.

Each workflow lists: steps → skill → artifact produced. Adapt, shorten or extend as the
request demands; always announce the plan before executing (master workflow step 3).

## W1 — Greenfield: from idea to reviewed specification

For "we need requirements for a new system".

1. Domain briefing → `elicitation-preparation` → domain introduction, key concepts
2. Stakeholder identification → `elicitation-preparation` → stakeholder table
3. Interview/workshop preparation → `elicitation-preparation` → interview guide / agenda
4. *(after elicitation happens)* Transcript refinement → `elicitation-transcription` → clean transcript
5. Requirement identification → `requirements-extraction` → candidate list with sources
6. Terminology alignment → `requirements-writing` → synonym table
7. Specification → `requirements-writing` → formulated, quality-checked requirements
8. Decomposition of coarse items → `requirements-writing` → system requirements / stories
9. Consistency check → `requirements-verification` → findings report, fixes via step 7
10. Tagging + trace links → `requirements-traceability` → tagged set + trace matrix

## W2 — Transcript to backlog

For "turn these interview notes into a backlog".

1. Refine transcription → `elicitation-transcription`
2. Identify requirements → `requirements-extraction`
3. Formulate as user stories incl. acceptance criteria → `requirements-writing`
4. Derive test cases for critical stories → `requirements-translation`
5. Tag for sprint planning (type, component, risk) → `requirements-traceability`

## W3 — Specification quality audit

For "review our spec".

1. Synonym table (detects terminology drift) → `requirements-writing`
2. Internal consistency analysis → `requirements-verification`
3. Reformulation of defective requirements → `requirements-writing`
4. Plain-language summary for sign-off by non-technical stakeholders → `requirements-translation`

## W4 — Change management

For "we got a change request".

1. Ensure trace links exist → `requirements-traceability` (skip if current)
2. Impact analysis → `change-impact-analysis` → affected artifacts, consequences, risks
3. Update affected requirements → `requirements-writing`
4. Re-verify consistency of the changed set → `requirements-verification`

## W5 — Legacy system: reverse engineering to spec

For "the code is the only documentation".

1. Generate requirements from source code → `requirements-translation`
2. Formulate/standardize the recovered requirements → `requirements-writing`
3. Compare specification with source code (closing the loop) → `requirements-verification`
4. Model key processes for stakeholder review → `requirements-translation`
5. Trace requirements ↔ code modules → `requirements-traceability`

## W6 — Stakeholder validation round

For "make this reviewable for the business side".

1. Explain requirements in simple language → `requirements-translation`
2. Generate personas for the main user groups → `requirements-translation`
3. Generate wireframes for UI-related requirements → `requirements-validation`
4. Collect feedback → feed corrections back via `requirements-writing`

## Composition rules

- Never skip a precondition (routing.md table) — insert the producing step instead.
- Steps 1–3 of W1 can run before any elicitation material exists; steps 4+ require it.
  The skills prepare and process elicitation — the conversations themselves happen with
  real stakeholders.
- After any step that *changes* requirements, schedule a `requirements-verification` pass
  before management steps (tagging, tracing, impact analysis) consume them.
- Shared context (glossary, assumptions log, open questions, traceability thread) flows
  through every step — see SKILL.md.
