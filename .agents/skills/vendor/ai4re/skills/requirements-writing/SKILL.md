---
name: requirements-writing
description: >
  Formulates, decomposes and standardizes requirements according to the IREB AI4RE Prompt
  Guide (cluster "Formulate"). Use when the user wants to write or rewrite a requirement in a
  standard format (user story, use case, IEEE/ISO 29148, SOPHIST/EARS), break a high-level
  requirement or goal down into detailed system requirements or SMART sub-goals, or build a
  synonym table to make terminology consistent across a specification. Triggers include:
  "specify/formulate this requirement", "rewrite as user story", "decompose/break down this
  requirement/goal", "synonym table", "make terminology consistent", "non-functional
  requirements", "nicht-funktionale Anforderungen", "ISO 25010", "Barrierefreiheit",
  "accessibility requirements", "WCAG", "Ausschreibung", "Anforderungskatalog".
version: 1.1.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Documentation
  ai4re-cluster: Formulate
  ai4re-use-cases: [Specify Requirement, Decompose Requirement, Generate Synonym Table]
---

# Requirements Writing

Turns raw stakeholder needs, vague statements and high-level goals into precise,
standard-conformant, quality-checked requirements — and keeps the terminology consistent.

## Provenance

`[AI4RE]` This skill implements the three use cases of the AI4RE Prompt Guide cluster
**Formulate** (IREB core activity: *Documentation*): *Specify Requirement*, *Decompose
Requirement*, *Generate Synonym Table*. Workflows, templates and pitfalls originate from the
guide. `[Supplementary: IREB CPRE Glossary, ISO/IEC/IEEE 29148:2018, INVEST, SMART]` Quality
criteria definitions and the EARS pattern are supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Formulate or reformulate a requirement in a standard format (user story + acceptance
  criteria, use case, IEEE/ISO 29148 style, SOPHIST template, EARS).
- Decompose a high-level requirement into detailed system requirements, or a main goal into
  SMART sub-goals.
- Create or update a synonym table / align terminology in a specification.

**Do not use when:**
- Requirements must first be *found* in transcripts or notes → `requirements-extraction`.
- Text should become a *model* (or vice versa), a persona, test cases or plain-language
  explanation → `requirements-translation`.
- The task is checking an existing set of requirements for contradictions →
  `requirements-verification`.
- A full glossary with definitions (not synonym mapping) is the goal — offer it as an
  extension of the synonym table and say the definitions are supplementary content.

## Roles

- **Claude acts as:** requirements specification expert and domain expert in the user's
  domain (ask for the domain if unknown) — dual-role prompting per AI4RE.
- **Typical users:** requirements engineers, business analysts, product owners; output must
  be readable for developers, testers and non-technical stakeholders alike.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which use case applies (specify / decompose / synonym table). If the
   request mixes them, sequence them: terminology → specify → decompose.
2. **Establish context.** Determine domain, system under consideration, target formulation
   standard and quality standard. If the user gave none:
   - Try to *detect* the formulation standard used in the input.
   - Otherwise propose the most appropriate standard (with a one-sentence rationale) and ask
     for confirmation before proceeding. `[AI4RE]` (interactive standard negotiation from
     *Specify Requirement*, steps 1–2b).
3. **Clarify or assume.** Ask targeted questions about system boundary, stakeholders and
   intended behavior when the input is ambiguous. If the user is unavailable or the gap is
   minor, proceed and prefix every guess with `Assumption:`.
4. **Execute** the use-case-specific procedure (below), applying the matching template from
   [references/templates.md](references/templates.md).
5. **Self-review.** Run the quality gates and the checklist from
   [references/checklists.md](references/checklists.md) against your own output. Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
6. **Deliver.** Output in the requested format, followed by: assumptions, open questions,
   detected risks, and a one-line reminder that the result is a draft requiring expert
   validation. `[AI4RE]` (general caution).

## Use cases

### 1. Specify Requirement `[AI4RE]`

Optimize the formulation of a single requirement.

1. Detect or negotiate the formulation standard (workflow step 2).
2. Reformulate the requirement in the chosen standard.
3. Validate against the chosen quality standard (default: IREB CPRE criteria for single
   requirements; INVEST for user stories). If criteria fail because information is missing,
   request it, then reformulate — iterate until it passes.
4. Log the rationale for every substantive change (traceability of the reformulation).

Template: *Specify Requirement* in [references/templates.md](references/templates.md).

### 2. Decompose Requirement `[AI4RE]`

Break down a high-level requirement into system requirements, or a main goal into sub-goals.

1. Confirm the decomposition target: **requirement → system requirements** (choose a
   formulation standard) or **goal → SMART sub-goals**.
2. State scope and assumptions explicitly before the decomposition (the guide's worked
   example leads with an "Assumptions & Scope" block — reproduce that practice).
3. Decompose so that every sub-element traceably contributes to the original requirement;
   keep one abstraction level per list (no mixing of business goals, features and UI details).
4. Cover functional *and* non-functional aspects when decomposing into system requirements.
   Structure NFRs by the ISO/IEC 25010:2023 categories plus *Randbedingungen* — walk all
   ten, cover or explicitly exclude each. For Austrian public-sector systems always include
   the accessibility block (WCAG AA / EN 301 549 / WZG). See
   [references/nfr-quality-model.md](references/nfr-quality-model.md).
5. Close with: risks / points to clarify, and a recommendation which subset forms an MVP.

Templates: *Decompose Into System Requirements* and *Decompose Goals Into Sub-Goals* in
[references/templates.md](references/templates.md).

### 3. Generate Synonym Table `[AI4RE]`

Build a terminology alignment table from a specification.

1. Read the provided specification. Identify technical terms, acronyms and domain-specific
   language — focus on terms used inconsistently; skip trivial synonyms.
2. Strict grounding rule: a primary term or synonym may only appear in the table if it is
   used in the provided document. Long forms of used abbreviations may be added even if the
   long form itself does not appear.
3. Output the markdown table: `Primary Term | Synonyms / Variants | Notes`, alphabetical by
   primary term. Flag context-dependent collisions (same acronym, two meanings) in Notes.
4. Recommend integrating the table into the specification and using primary terms
   consistently going forward.

Template: *Generate Synonym Table* in [references/templates.md](references/templates.md).

## Output formats

- **Requirements:** user story incl. acceptance criteria (Given/When/Then), use case
  (structured template), IEEE/ISO 29148-style "The system shall …", SOPHIST template, EARS
  `[Supplementary: EARS]` — as negotiated.
- **Decompositions:** numbered list of requirements in the chosen standard, preceded by
  *Assumptions & Scope*, followed by *Risks / Points to Clarify* and *Recommendation*.
- **Synonym table:** markdown table as specified above.
- Plain markdown unless the user requests another format (e.g. CSV for import).

## Quality gates

Check every produced requirement against `[Supplementary: IREB CPRE / ISO 29148]`:
**unambiguous, complete, consistent, verifiable/testable, atomic, traceable, comprehensible,
feasible, necessary**. For user stories additionally INVEST; for goals SMART. The full
operationalized checklists live in [references/checklists.md](references/checklists.md).

Two house rules apply to every requirement:

- **Self-contained — no cross-references.** The requirement text must be understandable on
  its own. Never refer to other requirements, IDs, chapters or sections ("see REQ-12",
  "as in the previous requirement", "gemäß Kapitel 3", "wie oben beschrieben", "analog zu
  …"). Restate the needed content instead, or split it into separate requirements.
  Relationships belong in trace attributes (parent, source), not in the text. Referencing
  an *external* standard or law (WCAG 2.1 AA, EN 301 549, DSGVO) is allowed.
- **NFRs are classified** by ISO/IEC 25010:2023 (+ *Randbedingungen*) — exactly one
  category per NFR, see [references/nfr-quality-model.md](references/nfr-quality-model.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- Ambiguity scan: weak words ("fast", "user-friendly", "etc.", "as appropriate"), passive
  voice hiding the actor, unresolved pronouns, universal quantifiers without bounds.
- Completeness scan: missing actor, trigger, object, measurement unit or error case.
- Cross-reference scan: no reference to other requirements, IDs, chapters or "above/below";
  rewrite until each requirement stands alone.
- NFR scan: every NFR carries one ISO/IEC 25010 category (or *Randbedingungen*);
  accessibility considered whenever there is a UI, document output or media.
- Consistency scan: terminology matches the synonym table / input vocabulary; one
  abstraction level per decomposition list.
- Grounding scan: no invented domain facts; every non-input-derived statement is marked
  `Assumption:` or listed as a suggestion.
- Intent scan: does the reformulation still express the stakeholder's original intent and
  value? (Pitfall: syntactically perfect, strategically empty.)

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing any of the three use cases |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/nfr-quality-model.md](references/nfr-quality-model.md) | Writing/decomposing NFRs; accessibility; Austrian public-sector catalogues |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
