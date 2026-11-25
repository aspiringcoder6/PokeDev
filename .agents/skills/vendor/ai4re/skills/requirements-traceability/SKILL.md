---
name: requirements-traceability
description: >
  Tags/classifies requirements and establishes trace links across artifacts according to the
  IREB AI4RE Prompt Guide (cluster "Assign"). Use when the user wants to classify a set of
  requirements into defined categories (e.g. functional vs. non-functional, ownership areas,
  ISO/IEC 25010 characteristics), or to trace a requirement backward to its sources
  (interviews, transcripts, presentations) and forward to downstream artifacts (design
  models, code modules, test cases, validation results). Triggers include: "tag/classify
  these requirements", "categorize the requirements", "traceability matrix", "trace this
  requirement", "where does this requirement come from", "which artifacts implement or test
  this requirement", "pre/post traceability".
version: 1.1.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Management
  ai4re-cluster: Assign
  ai4re-use-cases: [Tag Requirements, Trace Requirements]
---

# Requirements Traceability

Assigns requirements to categories and connects them to their source and downstream
artifacts — so every requirement stays classified, owned and traceable across the lifecycle.

## Provenance

`[AI4RE]` This skill implements the two use cases of the AI4RE Prompt Guide cluster
**Assign** (IREB core activity: *Management*): *Tag Requirements* and *Trace Requirements*.
The original guide titles the cluster page "Asign" [sic]; this repository uses the corrected
spelling "Assign". Workflows, templates, worked examples and pitfalls originate from the
guide. `[Supplementary: IREB CPRE Glossary, ISO/IEC/IEEE 29148:2018, Gotel & Finkelstein
1994]` Traceability terminology definitions (pre-/post-requirements-specification
traceability) and operationalized trace-link quality criteria are supplementary and marked
as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Classify requirements into exactly one category per requirement, using a defined taxonomy
  (requirement type, quality characteristic, ownership/team area, compliance domain).
- Trace one or more requirements to their sources ("pre" traceability: interviews,
  transcripts, presentations, contracts) and to downstream artifacts ("post" traceability:
  design models, code modules, test cases, validation results).
- Build a traceability matrix or find gaps in trace coverage (e.g. requirements without
  tests, requirements without an identifiable source).

**Do not use when:**
- The goal is to assess *what a proposed change affects* — trace links are input there, not
  the deliverable → `change-impact-analysis`.
- Requirements should be checked against each other for contradictions or consistency →
  `requirements-verification`.
- Requirements must be reformulated, decomposed or terminologically aligned →
  `requirements-writing` (its synonym table also feeds this skill's synonym-aware search).
- Requirements must first be *found* in transcripts or notes — extraction discovers new
  requirements; tracing locates evidence for existing ones → `requirements-extraction`.
- A requirement should be converted into a model, test cases, persona or plain language →
  `requirements-translation`.
- Stakeholder agreement that requirements match real needs is the question →
  `requirements-validation`.
- The task is preparing elicitation sessions or turning recordings into usable transcripts
  (which later become traceable source artifacts) → `elicitation-preparation`,
  `elicitation-transcription`.

## Roles

- **Claude acts as:** for tagging, an AI assistant that classifies software requirements
  into exactly one category (consistent, explainable, reproducible); for tracing, a
  requirements engineer mapping requirements to related artifacts. `[AI4RE]` Add domain
  expertise for the user's domain when category semantics depend on it (ask if unknown).
- **Typical users:** requirements engineers, requirements managers, product owners, QA
  leads; output must be auditable by reviewers and importable into RM tools.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which use case applies (tag / trace). If both are requested,
   sequence them: tag first (categories aid navigation), then trace per requirement.
2. **Establish context.** For tagging: obtain the category taxonomy — each category needs an
   ID, name, purpose description and include criteria. If the user provides none, propose a
   taxonomy (e.g. IREB requirement types, ISO/IEC 25010 characteristics `[AI4RE]`) and ask
   for confirmation before classifying. For tracing: collect the requirement(s) and all
   available artifacts; ask which artifact types exist (design, code, tests, validation) so
   absences can be reported deliberately.
3. **Clarify or assume.** Ask targeted questions when category boundaries overlap, when a
   requirement's intent is ambiguous, or when the artifact set looks incomplete. If
   proceeding anyway, prefix every guess with `Assumption:`.
4. **Execute** the use-case-specific procedure (below), applying the matching template from
   [references/templates.md](references/templates.md).
5. **Self-review.** Run the quality gates and the checklists from
   [references/checklists.md](references/checklists.md) against your own output. Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
6. **Deliver.** Output in the requested format, followed by: assumptions, open questions,
   detected risks (e.g. biased source selection), and a one-line reminder that the result is
   a draft requiring expert validation. `[AI4RE]` (general caution). If artifacts appear to
   contain confidential content, remind the user not to feed such data into external AI
   services.

## Use cases

### 1. Tag Requirements `[AI4RE]`

Assign each requirement to exactly one category — consistent, explainable, reproducible.

1. Validate the taxonomy before classifying: sharp definitions, include criteria per
   category, no unresolvable overlaps. If categories overlap conceptually (e.g.
   collaboration vs. permissions), report it and propose sharper include criteria before
   proceeding. For non-functional requirements without a user taxonomy, propose the
   ISO/IEC 25010:2023 set (+ *Randbedingungen*) from
   [references/templates.md](references/templates.md) and confirm it before use.
2. Apply the decision rules verbatim: a category matches if at least one include criterion
   clearly applies; exactly one match → select it; multiple matches → select the category
   representing the requirement's *primary goal*; primary goal undeterminable →
   `UNCLEAR`.
3. Apply the reasoning rules: cite the include criterion that triggered the primary
   category; state secondary matching categories explicitly; for `UNCLEAR`, explain why the
   intent is ambiguous and what information is missing.
4. Run a consistency pass: requirements that mean the same but are worded differently must
   land in the same category; surface-word traps ("quick", "efficient", "intuitive") must
   not flip a functional requirement into non-functional.
5. Output in the requested format (markdown table, CSV, Excel-ready).

Template: *Tag Requirements* in [references/templates.md](references/templates.md).

### 2. Trace Requirements `[AI4RE]`

Establish bidirectional trace links between a requirement and the provided artifacts.

1. Screen all provided artifacts. Identify (a) the requirement's source and (b) downstream
   artifacts such as design models, code modules, test cases and validation results.
2. Ground strictly on artifact *content*, never on file names. When referencing an artifact,
   identify document title and author(s) from the first page if available and meaningful.
3. For every link, give the exact location (page, section, slide, paragraph or timestamp)
   plus a direct quote or summary. If the requirement is not found or only partially
   addressed in an artifact class, state this explicitly.
4. Classify each link as **"pre"** (pre-requirements-specification traceability — source) or
   **"post"** (post-requirements-specification traceability — downstream artifact).
5. Search synonym-aware: literal word matching produces false negatives; expand key terms
   with synonyms before concluding "not found" (reuse an existing synonym table if the user
   has one). `[AI4RE]` (Pitfalls: Synonyms).
6. Close with: coverage of acceptance criteria (if the requirement has any), identified
   gaps, and a recommendation (e.g. links to record in the RM tool, missing tests to write,
   Definition-of-Done additions) — the guide's worked example models this closing.

Template: *Trace Requirements* in [references/templates.md](references/templates.md).

## Output formats

- **Classification list/table:** per requirement `ID | Category | Reasoning | Criterion
  cited | Secondary match` — as markdown table, CSV or Excel-ready CSV, as requested.
  `UNCLEAR` entries carry the ambiguity explanation and missing information.
- **Traceability report:** per requirement, a *Source Artefacts ("pre")* section and a
  *Downstream Artefacts ("post")* section, each entry with document, location, quote/summary
  and classification; then *Not Found in Provided Artefacts*, *Coverage of Acceptance
  Criteria* (table), *Gaps / Issues Identified*, *Recommendation*.
- **Traceability matrix** `[Supplementary: common RM practice]`: requirements × artifacts
  grid with link type (pre/post) per cell — offer when multiple requirements are traced.
- Plain markdown unless the user requests another format.

## Quality gates

- **Explainability** `[AI4RE]`: every classification cites the triggering include criterion;
  every trace link cites document, exact location and quote/summary.
- **Determinism/reproducibility** `[AI4RE]`: same input + same rules → same category;
  decision and reasoning rules applied verbatim, no ad-hoc judgment.
- **Groundedness** `[AI4RE]`: links rest on artifact content, not file names; no
  abstractions beyond what the evidence states.
- **Completeness of coverage** `[Supplementary: ISO/IEC/IEEE 29148:2018]`: bidirectional —
  both source and downstream directions addressed; absences reported explicitly, never
  silently skipped.
- **Single-category mapping** `[AI4RE]`: exactly one category per requirement (or
  `UNCLEAR`), supporting clear ownership and responsibility assignment.

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- Taxonomy scan: were overlapping or fuzzy categories flagged instead of silently resolved?
- Consistency scan: do semantically equivalent, differently worded requirements share a
  category? Any FR mislabeled as NFR because of surface words?
- Evidence scan: does every trace link have location + quote? Is anything inferred from a
  file name or from patterns "between the lines"? Downgrade over-abstractions to
  `Assumption:` or remove them.
- Coverage scan: is every requested artifact class either linked or explicitly reported as
  not found? Is source selection bias called out when the artifact set looks one-sided?
- Plausibility trap: does the output merely *look* clean? Spot-check 2–3 entries against the
  raw input before delivering (false confidence from clean-looking results is a named
  pitfall).
- Draft label: is the result marked as a draft requiring expert validation?

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing either use case |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check of tags or trace links |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
