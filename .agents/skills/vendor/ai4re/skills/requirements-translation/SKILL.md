---
name: requirements-translation
description: >
  Converts requirements between representations according to the IREB AI4RE Prompt Guide
  (cluster "Translate"): text to formal models (UML, BPMN, SysML as PlantUML/Mermaid/XML),
  models back to natural-language requirements, requirements to test cases, complex specs
  to plain-language stakeholder summaries, elicitation data to personas, and source code to
  reverse-engineered requirements. Use when the user wants to "generate a diagram/model from
  these requirements", "turn this UML/BPMN diagram into user stories", "explain these
  requirements in simple language / for executives", "create a persona from this interview",
  "derive/generate test cases", or "extract requirements from this source code".
version: 1.1.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Documentation
  ai4re-cluster: Translate
  ai4re-use-cases: [Generate Model From Text, Generate Text From Model, Explain Requirements in Simple Language, Generate Persona, Generate Test Cases, Generate Requirements From Source Code]
---

# Requirements Translation

Converts requirements between representations — text ↔ models, requirements → test cases,
complex specs → plain language, elicitation data → personas, source code → requirements —
while preserving meaning and keeping traceability across artifacts and audiences.

## Provenance

`[AI4RE]` This skill implements the six use cases of the AI4RE Prompt Guide cluster
**Translate** (IREB core activity: *Documentation*): *Generate Model From Text*, *Generate
Text From Model*, *Explain Requirements in Simple Language*, *Generate Persona*, *Generate
Test Cases*, *Generate Requirements From Source Code*. Workflows, templates and pitfalls
originate from the guide. `[Supplementary: Mermaid, PlantUML, IREB CPRE Glossary,
ISO/IEC/IEEE 29148:2018, ISO/IEC/IEEE 29119]` Notation guidance for textual model syntax
and quality-criteria operationalizations are supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Transform textual requirements, scenarios or workflows into a formal model (UML, BPMN,
  SysML v1/v2) delivered as importable textual notation (PlantUML, Mermaid, BPMN XML,
  SysML v2 textual syntax).
- Turn a model/diagram into natural-language requirements, use cases or scenarios.
- Rewrite or summarize requirements in plain language for a specific stakeholder group.
- Create a persona draft from interviews, workshop transcripts, feedback or survey results.
- Derive structured test cases (positive, negative, edge) from requirements.
- Reverse-engineer functional and non-functional requirements from existing source code.

**Do not use when:**
- A requirement must be *formulated or decomposed* in a standard (user story, IEEE 29148,
  SOPHIST, EARS) → `requirements-writing`.
- Requirements must first be *found* in transcripts, notes or documents →
  `requirements-extraction`.
- An existing model or specification must be *checked* for consistency, contradictions or
  quality defects → `requirements-verification`.
- Wireframes or mockups for stakeholder validation are the goal →
  `requirements-validation`.
- The task is preparing interviews/workshops → `elicitation-preparation`, or transcribing
  their recordings → `elicitation-transcription`.
- The question is what a change *affects* → `change-impact-analysis`; establishing or
  maintaining trace links between artifacts → `requirements-traceability`.

## Roles

- **Claude acts as** (switch per use case, per the AI4RE templates): MBSE and modeling
  expert (UML, BPMN, SysML v1/v2) for text↔model; expert business analyst specializing in
  stakeholder communication for plain-language explanation; experienced UX designer for
  personas; requirements analysis and software testing expert for test cases; specialist in
  software analysis and requirements engineering for reverse engineering.
- **Typical users:** requirements engineers, business analysts, product owners; output
  audiences range from modeling-tool users to executives, end users and testers — always
  ask who the output is for.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which of the six use cases applies. If the request chains them
   (e.g. code → requirements → test cases), sequence them and confirm the chain with the
   user.
2. **Establish context.** Determine the system under consideration, domain, source artifact
   and target representation (modeling language + diagram type, formulation standard,
   stakeholder group, persona role, or spec structure). Resolve every template variable
   before executing; unresolved variables become clarifying questions.
3. **Clarify or assume.** Ask targeted questions when the source artifact is ambiguous or
   incomplete. If proceeding anyway, prefix every guess with `Assumption:`. `[AI4RE]`
   (hallucination/overgeneration pitfalls across the cluster). If the input suggests
   confidential material (source code, interview transcripts, customer data), remind the
   user not to feed such data into external AI services.
4. **Chunk large inputs.** Break large specifications, models or code bases into manageable
   groups before translating; translate group by group and let the user pick the starting
   group where the template prescribes it. `[AI4RE]` (size/complexity and amount-of-data
   pitfalls).
5. **Execute** the use-case-specific procedure (below), applying the matching template from
   [references/templates.md](references/templates.md).
6. **Self-review.** Run the quality gates and the matching checklist from
   [references/checklists.md](references/checklists.md) against your own output. For
   generated model code, verify syntax; if it fails, self-correct and re-check. Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
7. **Deliver.** Output in the requested format, followed by: a validation note with
   assumptions, identified gaps, open questions and risks, and a one-line reminder that the
   result is a draft requiring expert validation. `[AI4RE]` (general caution).

## Use cases

### 1. Generate Model From Text `[AI4RE]`

Convert textual requirements, use cases or scenarios into a formal model.

1. Confirm modeling language (`UML`, `BPMN`, `SysML v1`, `SysML v2`) and diagram type.
2. Group requirements that belong in one diagram (consider the diagram type); present the
   groups with a short rationale and ask the user which group to start with.
3. For the selected group, identify all relevant elements of the diagram type (actors,
   lifelines, messages, fragments, guards, …) and list them in a table with explanations.
4. Produce the model in importable textual notation — PlantUML, Mermaid, BPMN XML or
   SysML v2 textual syntax. Prefer Mermaid or PlantUML when the user has no tool
   constraint, as they render directly in markdown toolchains `[Supplementary: Mermaid,
   PlantUML]`.
5. Close with a validation note: assumptions made, gaps in the source text, cross-cutting
   concerns not modeled.

Template: *Generate Model From Text* in [references/templates.md](references/templates.md).

### 2. Generate Text From Model `[AI4RE]`

Convert a model (diagram image or textual notation) into natural-language requirements.

1. Confirm the target formulation standard (`[FORMULATION]`: user story, use case, IEEE,
   SOPHIST, other).
2. Extract all relevant model elements into text first (actors, components, scenarios,
   control structures) — this makes the translation traceable.
3. Generate the requirements from the extracted elements; derive acceptance criteria from
   interactions and guards where the standard supports them.
4. Guard against semantic loss: carry multiplicities, guards, triggers, alt/opt/loop
   fragments into the text; do not soften them. Flag visual cues (colors, stereotypes) that
   cannot be translated. `[AI4RE]` (semantic-loss pitfall).
5. Close with a validation note: assumptions, gaps, interpretations.

Template: *Generate Text From Model* in [references/templates.md](references/templates.md).

### 3. Explain Requirements in Simple Language `[AI4RE]`

Rewrite or summarize requirements for a specific stakeholder group.

1. Require a concrete `[STAKEHOLDER_GROUP]` — "simple" depends on the audience; never
   simplify for an unspecified reader.
2. Choose the variant: **per-requirement translation** (bulleted list, each item with a
   plain description plus a "What this means for you:" impact line) or **thematic summary**
   (group requirements into themes, summarize by theme, not by individual requirement).
3. Focus on the *what* and the *why* from the audience's perspective; omit the *how*.
4. Preserve meaning strictly: keep modal verbs' obligation level (never turn "must" into
   "should"/"can"), keep conditions and constraints, explain technical terms instead of
   deleting them, and do not soften security, privacy or compliance statements. `[AI4RE]`
   (oversimplification and modal-verb pitfalls).
5. Where relevant, state limitations or implementation considerations — no unbroken
   positivity, no empty business phrases.

Templates: *Explain Requirements — Translate* and *Explain Requirements — Summary* in
[references/templates.md](references/templates.md).

### 4. Generate Persona `[AI4RE]`

Create a persona draft from stakeholder input (interviews, transcripts, feedback, surveys).

1. Confirm the persona's job/role (`[ROLE]`) and whether an image description is wanted.
2. Generate exactly one persona, strictly based on the provided input, using the fixed
   structure: fictional name, age, job/role, main goals, day-to-day challenges, technology
   affinity, values/attitude towards change, specific expectations towards the system.
3. Avoid stereotypes and clichés. Use hypotheses only if necessary and label each one
   explicitly for later validation.
4. Keep it under 200 words, plain text. Recommend validation with stakeholders and UX or
   domain experts.

Template: *Generate Persona* in [references/templates.md](references/templates.md).

### 5. Generate Test Cases `[AI4RE]`

Derive structured test cases from requirements.

1. Check input quality first: vague requirements produce misaligned test cases — flag weak
   or ambiguous requirements before deriving tests from them. `[AI4RE]` (poor-requirements
   pitfall).
2. For each requirement, generate one or more test cases including positive, negative and
   edge cases where applicable.
3. Output one table: `Test Case ID | ID of the tested Requirement | Description | Input |
   Expected Output | Type (Positive/Negative/Edge)`. Keep requirement IDs from the source
   for traceability.
4. State which test types are *not* covered (security, performance, usability, …) — the
   table supplements, never replaces, comprehensive test design.
5. For large requirement sets, split into sub-tasks per module/feature to avoid truncated
   output.

Template: *Generate Test Cases* in [references/templates.md](references/templates.md).

### 6. Generate Requirements From Source Code `[AI4RE]`

Reverse-engineer a requirements specification from existing code.

1. Assess the input's completeness: snippets omit invocation context, dependencies and
   architecture. State what you can and cannot infer; ask for missing modules,
   configuration or entry points when they materially affect the result.
2. Identify functionalities, rules, constraints and dependencies; distinguish user-facing
   features from utility/helper logic (do not promote helpers to requirements).
3. Derive functional requirements and non-functional requirements in clear, testable,
   implementation-independent language; where the code reveals no NFRs, say so instead of
   inventing them.
4. Output the structured specification: *Introduction* (context and assumptions),
   *Functional Requirements* (numbered, title + description), *Non-Functional Requirements*
   (grouped by ISO/IEC 25010:2023 category + *Randbedingungen*, see
   [references/templates.md](references/templates.md)), *Glossary*, *Traceability Note* (which code informed each
   requirement).
5. Mark every requirement whose scope exceeds the visible code as `Assumption:` — no
   overgeneralization from partial code.

Template: *Generate Requirements From Source Code* in
[references/templates.md](references/templates.md).

## Output formats

- **Models:** importable textual notation — PlantUML, Mermaid `[Supplementary]`, BPMN XML,
  SysML v2 textual syntax — preceded by a requirement-grouping list and a diagram-element
  table, followed by a validation note.
- **Requirements from models:** the chosen formulation standard (user story incl.
  acceptance criteria, use case, IEEE, SOPHIST), preceded by the textual element
  extraction, followed by validation notes.
- **Plain-language output:** bulleted list with "What this means for you:" lines, or a
  thematic structured summary — per the chosen template variant.
- **Persona:** plain-text profile, fixed 8-field structure, < 200 words, hypotheses
  labeled; optional portrait description.
- **Test cases:** one markdown table with the six columns listed above.
- **Reverse-engineered specification:** Introduction · Functional Requirements ·
  Non-Functional Requirements · Glossary · Traceability Note.
- Plain markdown unless the user requests another format (e.g. CSV/XLSX export for test
  management, `.puml`/`.mmd` files for modeling tools).

## Quality gates

Every translation must be `[AI4RE-adapted]` (derived from the cluster's pitfall sections):
**meaning-preserving** (no changed, added or removed intent; obligation levels intact),
**traceable** (every output element maps to an input element; suggested/inferred content
separated and marked), **grounded** (no invented details where the source is silent),
**syntactically valid** (model code passes notation syntax), and **audience-appropriate**
(representation and language match the declared target group).
`[Supplementary: IREB CPRE / ISO 29148]` Generated requirements additionally meet:
unambiguous, complete, atomic, verifiable, consistent. `[Supplementary: ISO/IEC/IEEE
29119]` Test cases specify preconditions/input and expected result explicitly. The full
operationalized checklists live in [references/checklists.md](references/checklists.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- Fidelity scan: compare output to source element by element — nothing dropped, softened
  (guards, multiplicities, modal verbs, conditions) or added without an `Assumption:` mark.
- Grounding scan: every persona trait, model element, test expectation and derived
  requirement traces to the input; hypotheses and inferences are labeled.
- Syntax scan: PlantUML/Mermaid/BPMN XML/SysML output is syntactically valid; self-correct
  on error before delivering.
- Coverage scan: test cases include negative and edge cases where applicable; uncovered
  test types named. Reverse-engineered specs state NFR gaps instead of hiding them.
- Audience scan: language, detail level and focus match the declared stakeholder group; no
  vague business phrases without concrete linkage to requirements.
- Draft label: output is marked as a draft requiring expert (domain/UX/test/architecture)
  validation.

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing any of the six use cases |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
