---
name: requirements-extraction
description: >
  Identifies candidate requirements in elicitation material according to the IREB AI4RE
  Prompt Guide (cluster "Extract"). Use when the user has interview transcripts, workshop
  notes, emails, meeting minutes or other stakeholder documents and wants to surface the
  requirements hidden in them: extract candidate requirements with traceable source quotes,
  classify them (functional / quality / constraint), group them by topic, and spot gaps and
  interdependencies. Triggers include: "extract/identify requirements from this
  transcript/notes/email", "what requirements are in this document", "find candidate
  requirements", "analyze this stakeholder input".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Elicitation
  ai4re-cluster: Extract
  ai4re-use-cases: [Identify Requirements]
---

# Requirements Extraction

Surfaces candidate requirements from elicitation material — transcripts, notes, emails,
documents — with a verbatim source reference for every candidate, plus classification,
grouping, and gap analysis.

## Provenance

`[AI4RE]` This skill implements the use case of the AI4RE Prompt Guide cluster **Extract**
(IREB core activity: *Elicitation*): *Identify Requirements*. The template, the two-column
traceability format, the worked example and the pitfalls originate from the guide.
`[AI4RE-adapted]` The classification (functional / quality / constraint), topic grouping and
gap analysis steps operationalize the guide's RE task description. `[Supplementary: IREB
CPRE Glossary, ISO/IEC/IEEE 29148:2018]` Quality criteria definitions are supplementary and
marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Identify candidate requirements in stakeholder input (interview transcript, workshop
  notes, emails, support tickets, meeting minutes, existing documents).
- Classify extracted statements into functional requirements, quality requirements and
  constraints, and group them by feature or topic.
- Recognize recurring patterns across stakeholder input and spot gaps, contradictions or
  interdependencies in the elicited material.

**Do not use when:**
- The input is a raw, noisy audio transcript that still needs cleanup (speaker labels,
  filler removal, correction of transcription errors) → run `elicitation-transcription`
  FIRST, then extract from the cleaned transcript.
- The candidates are already identified and must now be *formulated* in a standard
  (user story, use case, IEEE/ISO 29148, SOPHIST, EARS), decomposed, or terminologically
  aligned → `requirements-writing`.
- The elicitation session itself still needs to be planned (interview questions, workshop
  agenda) → `elicitation-preparation`.
- Requirements should be transformed into another representation (model, persona, test
  cases, plain-language explanation) → `requirements-translation`.
- Extracted requirements must be checked against stakeholder needs and intent →
  `requirements-validation`; checked for internal contradictions and quality defects →
  `requirements-verification`.
- The task is assessing the impact of a change on an existing set of requirements →
  `change-impact-analysis`; or establishing/maintaining trace links across artifacts →
  `requirements-traceability` (this skill only creates the initial candidate-to-source
  link).

## Roles

- **Claude acts as:** expert in requirements engineering `[AI4RE]`; additionally a domain
  expert in the user's domain when nuanced terminology is involved (ask for the domain if
  unknown) `[AI4RE-adapted]`.
- **Typical users:** requirements engineers, business analysts, product owners processing
  elicitation results; output must remain traceable and reviewable for the stakeholders who
  produced the input.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify the input type (transcript, notes, email thread, document, mixed).
   If the input is an uncleaned raw transcript, recommend `elicitation-transcription` first
   and proceed only if the user declines. If the input appears to contain personal or
   confidential data, remind the user not to feed such material into external AI services
   without clearance and suggest anonymization. `[AI4RE]` (general caution).
2. **Establish context.** Determine domain, system under consideration and business goals —
   relevance judgments depend on them (pitfall: *lack of business context*). Confirm the
   output format (default: the AI4RE two-column table; extended table on request).
3. **Clarify or assume.** Ask targeted questions when scope, stakeholder roles or
   domain-specific terms are ambiguous. If the user is unavailable or the gap is minor,
   proceed and prefix every guess with `Assumption:`.
4. **Execute** the *Identify Requirements* procedure (below), applying the template from
   [references/templates.md](references/templates.md).
5. **Self-review.** Run the quality gates and the checklist from
   [references/checklists.md](references/checklists.md) against your own output — above all
   the grounding scan (every reference quote must occur verbatim in the input) and the
   coverage scan (re-read the input for missed requirement-bearing statements). Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
6. **Deliver.** Output in the agreed format, followed by: detected gaps and
   interdependencies, assumptions, open questions, and a one-line reminder that the result
   is a set of *candidate* requirements — a draft requiring stakeholder validation and
   expert review. `[AI4RE]` (conclusion + general caution).

## Use cases

### 1. Identify Requirements `[AI4RE]`

Analyze stakeholder input and identify the relevant requirements.

1. Read the entire input once for context before extracting anything — relevance and
   grouping decisions need the whole picture.
2. Extract candidate requirements statement by statement. Write each as a clear, concise
   statement, ideally in the user story template ("As a [role], I want [feature], so that
   [benefit]"); pair it with a verbatim quote from the input as its reference. Where the
   user story template does not fit (complex technical or regulatory content), use a plain
   declarative statement and flag it for detailed specification via `requirements-writing`
   (pitfall: *reliance on user story template*).
3. Classify each candidate as functional requirement, quality requirement or constraint;
   group candidates by feature or topic. `[AI4RE-adapted]` (from the RE task description).
   Do not force a category — mark candidates that span categories or carry essential
   context instead of truncating them (pitfall: *over-categorization*).
4. Recognize patterns: recurring pain points, repeated needs across speakers or documents,
   and interdependencies between candidates (pitfall: *missing interdependencies*).
5. Spot gaps: requirement types absent from the input (e.g., no quality requirements, no
   error handling), stakeholder questions left unanswered, and contradictions between
   statements. List them as open questions — never fill gaps with invented content.
6. Close with recommendations, as in the guide's worked example: validate the candidates
   with subject matter experts and prioritize (e.g., MoSCoW); refine key candidates with
   acceptance criteria and measurable KPIs; check for organization-specific context (e.g.,
   systems in use) that should become additional requirements.

Template: *Identify Requirements* in [references/templates.md](references/templates.md).

## Output formats

- **Candidate requirements table** `[AI4RE]` (default): markdown table
  `Requirement | Reference` — column 1 a clear, concise statement (ideally user story
  format), column 2 a verbatim quote from the input.
- **Extended extraction table** `[AI4RE-adapted]` (on request):
  `ID | Requirement | Reference | Type (functional / quality / constraint) | Topic | Notes`.
- **Gaps & open questions:** bulleted list after the table — missing coverage,
  contradictions, unresolved ambiguities.
- **Patterns & interdependencies:** short bulleted summary of recurring themes and
  dependencies between candidates.
- **Recommendation block** `[AI4RE]`: validation, prioritization and refinement next steps.
- Plain markdown unless the user requests another format (e.g. CSV for backlog import).

## Quality gates

Check the extraction against these criteria before delivery:

- `[AI4RE]` **Traceable** — every candidate has a verbatim reference quote from the input;
  merged duplicates cite all their sources.
- `[AI4RE]` **Grounded** — nothing extracted that the input does not support; suggestions
  and inferences are separated from extracted content and marked.
- `[AI4RE]` **Intent-preserving** — the candidate expresses what the stakeholder meant, not
  a plausible-sounding generalization (pitfall: *misinterpretation*).
- `[Supplementary: IREB CPRE / ISO 29148]` **Atomic and comprehensible** — one candidate per
  row; readable without insider knowledge beyond the input. (Full formulation quality is
  the job of `requirements-writing`, not a gate here.)
- `[AI4RE-adapted]` **Complete relative to input** — every requirement-bearing statement in
  the input is either extracted or consciously excluded; gaps are named, not papered over.

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- **Grounding scan:** every Reference quote occurs verbatim (or as a clearly marked
  condensation) in the input; no candidate lacks a reference.
- **Coverage scan:** re-read the input end to end — any statement expressing a need,
  problem, wish or constraint without a corresponding table entry?
- **Interpretation scan:** domain-specific terms and nuanced statements — is my reading
  certain, or should the candidate carry an `Assumption:` or open question?
- **Categorization scan:** any candidate forced into a single category although it spans
  several, or stripped of essential context?
- **Dependency scan:** are interdependencies between candidates identified and listed?
- **Relevance scan:** does each candidate plausibly serve the stated business goals? If
  goals are unknown, is that flagged as an open question rather than guessed?

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing the use case |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting the template to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
