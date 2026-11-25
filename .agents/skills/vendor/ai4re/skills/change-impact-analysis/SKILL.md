---
name: change-impact-analysis
description: >
  Analyzes the impact of change requests on requirements and related artifacts according to
  the IREB AI4RE Prompt Guide (cluster "Align"). Use when the user presents a change request
  (CR) and wants to know which requirements, documents, models, modules, systems or
  interfaces are affected, what must be adapted where, who is responsible, and which risks,
  dependencies and validation needs arise — before the change is committed. Triggers include:
  "change request", "impact analysis", "what is affected by this change", "which
  requirements/documents need to be updated", "assess this change", "change package".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Management
  ai4re-cluster: Align
  ai4re-use-cases: [Analyze Change Request Impact]
---

# Change Impact Analysis

Turns a change request plus the surrounding artifacts into a complete, source-cited impact
table — affected requirements, exact edit locations, proposed actions, owners, risks and
missing artifacts — so the change can be planned and communicated before anyone commits to it.

## Provenance

`[AI4RE]` This skill implements the single use case of the AI4RE Prompt Guide cluster
**Align** (IREB core activity: *Management*): *Analyze Change Request Impact*. The role,
task steps, output table, worked example and pitfalls originate from the guide.
`[Supplementary: IREB CPRE Glossary, ISO/IEC/IEEE 29148:2018]` Definitions of impact
analysis and requirements-management quality criteria are supplementary and marked as such
where used.

## When to use / when not to use

**Use when the user wants to:**
- Determine which requirements, documentation elements, models, modules, systems or
  interfaces a change request affects.
- Derive the necessary adaptations per affected artifact, with exact edit locations and
  responsible persons or departments.
- Surface risks, dependencies, validation needs and missing artifacts *before* deciding on
  or implementing a change.

**Do not use when:**
- Trace links between requirements and artifacts must first be *established* →
  `requirements-traceability` (do that FIRST — impact analysis builds on trace links; an
  analysis without them degrades to text matching).
- An existing requirement set should be checked for contradictions or inconsistencies
  without a triggering change request → `requirements-verification`.
- Affected requirements must be *rewritten* after the analysis → `requirements-writing`.
- Requirements should be validated against stakeholder needs → `requirements-validation`.
- Requirements must be converted between text, models, personas or test cases →
  `requirements-translation`.
- Requirements must first be *found* in transcripts or notes → `requirements-extraction`.
- The task is preparing or transcribing elicitation sessions → `elicitation-preparation`
  or `elicitation-transcription`.

## Roles

- **Claude acts as:** specialist in impact analysis for requirements and associated
  documentation — responsible for identifying all affected requirements, related
  documentation elements and, if known, impacted modules, systems or interfaces. `[AI4RE]`
- **Typical users:** requirements engineers managing the change process and coordinating
  updates across requirements, system documentation and design artifacts; also product
  owners, architects and change control boards consuming the result.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Isolate the change request text and inventory the provided artifacts
   (requirements lists, use cases, business concepts, UI mockups, process or UML diagrams,
   interface specs). Note each artifact's exact file name or path — all later citations use
   these names. `[AI4RE]`
2. **Establish context.** Check whether the inputs that make analysis reliable are present:
   traceability matrix, architecture diagram, system boundary definition, glossary,
   business rule document, interface/service specifications. Request what is missing (see
   [references/checklists.md](references/checklists.md), gate 1); if the user cannot supply
   it, proceed and record the gap as a stated limitation of the analysis. `[AI4RE]`
   (pitfall mitigations). If artifacts contain confidential business or customer data and
   an external AI service is in play, remind the user of the sensitive-data risk.
3. **Clarify or assume.** Ask targeted questions when the change request is ambiguous
   (undefined terms, unclear scope, implicit business rules). If a gap is minor, proceed
   and prefix every guess with `Assumption:` — especially for business-rule
   interpretations, which are never guessed silently. `[AI4RE]` (pitfall: misinterpreting
   business rules).
4. **Execute** the use-case procedure below, applying the template from
   [references/templates.md](references/templates.md). Ground strictly on the provided
   artifacts: every claimed impact cites its source by exact file name/path; impacts
   inferred without artifact evidence are labeled as such (e.g. `missing artifacts`,
   `connected systems`).
5. **Self-review.** Run the coverage and quality checklists from
   [references/checklists.md](references/checklists.md) against your own output. Fix what
   fails; whatever cannot be resolved from the given input becomes an open question.
6. **Deliver.** Output the impact table and companion sections (below), followed by
   assumptions, open questions, risks — and a one-line reminder that the analysis is a
   draft requiring validation by domain experts, developers and (for rule changes)
   Legal/Compliance before the change package is committed. `[AI4RE]`

## Use cases

### 1. Analyze Change Request Impact `[AI4RE]`

Identify and evaluate all impacts of a change request on requirements and related
documentation, so the requirements engineer can plan and communicate necessary actions,
prevent inconsistencies, and maintain up-to-date requirements.

1. Screen the provided change request description and its context (e.g., related
   requirements, business concepts, UI mockups, process or UML diagrams).
2. Identify the change request elements (decompose the CR into its atomic changes) and the
   affected requirements.
3. For each affected requirement, determine the associated documentation artifacts that
   need to be updated.
4. Propose actions or adaptations to maintain consistency and correctness within the
   artifacts; show the exact location where the artifact should be changed; name the
   responsible persons or departments (if known).
5. Highlight risks, dependencies and validation needs.
6. Also suggest missing artifacts (documents that should exist but were not provided or do
   not exist yet, e.g. a business rule catalog entry).
7. Sweep systematically across impact categories — UI, service/logic, data model, API,
   integration, reports — so structural and logical impacts are found, not just textual
   ones. `[AI4RE]` (pitfall mitigation).
8. Normalize granularity: group findings at consistent abstraction levels (requirement /
   artifact / system-interface) so scope, estimation and ownership stay clear. `[AI4RE]`
   (pitfall mitigation).

Template: *Analyze Change Request Impact* in
[references/templates.md](references/templates.md).

## Output formats

- **Impact table** `[AI4RE]` — one row per impact; a CR element may map to multiple rows.
  Columns: `Impacted Requirement / Artifact | Source | Type of Impact | Proposed Action |
  Dependencies / Risks | Comments`. Source names the information type (e.g. given input,
  missing artifacts, connected systems) and cites the exact file name or path.
- **CR element list** `[AI4RE-adapted]` — the change request decomposed into numbered
  atomic changes, placed before the table (practice from the guide's worked example).
- **Edit points by document** `[AI4RE-adapted]` — per source document, the concrete edits
  (worked-example practice: "Additional actions and exact edit points (by document)").
- **Responsibilities** `[AI4RE-adapted]` — proposed owner per action stream (RE/Product,
  Legal/Compliance, Architecture/Backend, UX/UI, QA/Test, Integration, Release), only
  where derivable or explicitly marked as a suggestion.
- **Risks, dependencies & validation needs** and **suggested missing artifacts** —
  mandatory closing sections; optionally a **validation checklist before release**
  `[AI4RE-adapted]`.
- Plain markdown unless the user requests another format (e.g. CSV for import into a
  change management tool).

## Quality gates

`[AI4RE]` The analysis must improve completeness of identified impacts, enhance
transparency, and support consistent handling of changes while maintaining requirements
quality. Concretely, check every delivery for: **completeness** (all impact categories
swept; hidden dependencies searched via trace links and diagrams), **groundedness** (every
impact cites its source artifact or is labeled inferred/missing), **actionability** (every
row has an exact edit location and a concrete proposed action), **consistent granularity**
(fixed abstraction levels, clear ownership), and **consistency preservation**
`[Supplementary: ISO/IEC/IEEE 29148:2018]` (proposed actions leave no contradictions or
orphaned references behind). The operationalized checklists live in
[references/checklists.md](references/checklists.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- **Hidden-dependency scan:** did I check cross-artifact relationships beyond explicit
  text matches (trace matrix, architecture, interfaces)? If those inputs were missing, is
  that limitation stated? `[AI4RE]`
- **Business-rule scan:** is any changed text actually a legal/compliance-critical
  constraint? If so, is Product Owner / Legal validation flagged instead of treating it as
  cosmetic wording? `[AI4RE]`
- **Logic-vs-structure scan:** for every UI/text/diagram impact, did I ask what
  service-level logic, data model or API contract sits behind it? Category checklist (UI,
  Service, Data Model, API, Integration, Reports) fully swept? `[AI4RE]`
- **Granularity scan:** no mixing of high-level and fine-grained impacts in one list;
  findings categorized into fixed levels. `[AI4RE]`
- **Grounding scan:** every source citation uses the exact file name/path; nothing invented;
  inferred impacts and missing artifacts explicitly labeled; guesses prefixed `Assumption:`.
- **Completeness of the deliverable:** risks/dependencies/validation needs present; missing
  artifacts suggested; draft-not-decision reminder included.

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing the use case |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check of an impact analysis |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting the template to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
