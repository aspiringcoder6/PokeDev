---
name: requirements-verification
description: >
  Verifies internal consistency and alignment of requirements artifacts according to the
  IREB AI4RE Prompt Guide (cluster "Verify"). Use when the user wants to find
  contradictions, duplicates, dependency gaps or terminology clashes within a set of
  requirements, check two interconnected UML models (class, sequence, activity, state
  machine diagrams) against each other, or compare a specification with its source code
  to find missing, altered or extra behavior. Triggers include: "check for
  contradictions/inconsistencies", "are these requirements consistent", "compare these
  diagrams/models", "does the code match the spec", "spec vs implementation",
  "discrepancy analysis", "find duplicates in the specification".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Validation
  ai4re-cluster: Verify
  ai4re-use-cases: [Analyze Requirements Consistency, Check Model Consistency, Compare Specification With Source Code]
---

# Requirements Verification

Turns a specification, a pair of models, or a spec-plus-codebase into a structured,
categorized findings report: contradictions, duplicates, gaps and misalignments — each
with an actionable fix suggestion.

## Provenance

`[AI4RE]` This skill implements the three use cases of the AI4RE Prompt Guide cluster
**Verify** (IREB core activity: *Validation*): *Analyze Requirements Consistency*, *Check
Model Consistency*, *Compare Specification With Source Code*. Templates, detection
taxonomies, output formats and pitfalls originate from the guide.
`[Supplementary: ISO/IEC/IEEE 29148:2018, IREB CPRE Glossary]` Operationalized
consistency criteria in the checklists are supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Detect and classify conflicts, redundancies, dependency gaps, terminology
  inconsistencies or implied coverage holes *within or across* requirements documents.
- Check consistency between two interconnected UML diagrams (class, sequence, activity,
  state machine) — as images or code-based artifacts (PlantUML, Mermaid).
- Compare a requirements specification against source code and report missing, altered
  or additional behavior (e.g. before an audit or release).

**Do not use when:**
- Stakeholders should confirm that requirements capture their *needs* (e.g. via
  wireframes) — that is validation, not verification → `requirements-validation`.
- The findings should be *fixed* — rewrite, decompose or align terminology →
  `requirements-writing`.
- Models or test cases must first be *generated* from text (or vice versa) →
  `requirements-translation`.
- The question is what a proposed *change* would affect → `change-impact-analysis`.
- Trace links between artifacts should be *built or maintained* (not checked for
  contradictions) → `requirements-traceability`.
- Requirements must first be *found* in raw material → `requirements-extraction`;
  for interview prep or transcripts → `elicitation-preparation`,
  `elicitation-transcription`.

## Roles

- **Claude acts as** (per use case, per AI4RE): expert in requirements engineering and
  analysis (consistency analysis) · MBSE and modeling expert specializing in UML (model
  consistency) · expert in code analysis and software requirements validation
  (spec-vs-code).
- **Typical users:** requirements engineers, business analysts, QA engineers, auditors,
  architects; output must be readable for developers and non-technical reviewers alike.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which use case applies (requirements consistency / model
   consistency / spec-vs-code) and confirm the artifacts to compare are actually
   provided. Missing artifacts are the first clarifying question — never verify against
   imagined content.
2. **Establish context.** Determine domain, system under consideration, and — for
   multi-document input — the abstraction level of each artifact (system vs. component
   level, document names, trace references). `[AI4RE]` Decomposed requirements at
   different levels are *legitimately* similar; without level metadata they produce
   false duplicates. Ask for or annotate levels before comparing.
3. **Clarify or assume.** Ask targeted questions when scope is ambiguous (e.g. which
   requirements are relevant to the given code, whether both diagrams describe the same
   system boundary). If proceeding anyway, prefix every guess with `Assumption:`.
4. **Assess input size.** For large inputs (hundreds of requirements, complex diagrams,
   large codebases), warn about attention limits ("lost in the middle"), propose
   chunked or iterative runs, and recommend a fresh session per comparison iteration.
   `[AI4RE]` (pitfalls of all three use cases).
5. **Execute** the use-case-specific procedure (below), applying the matching template
   from [references/templates.md](references/templates.md). Ground every finding in
   exact quotes / element names / code references from the input — never paraphrase
   evidence.
6. **Self-review.** Run the quality gates and the checklist from
   [references/checklists.md](references/checklists.md) against your own findings.
   Remove findings you cannot evidence; unresolvable doubts become open questions.
7. **Deliver.** Output in the use case's format, followed by: assumptions, open
   questions, coverage caveats (what was *not* checked), and a reminder that the report
   is a draft — AI may miss inconsistencies and flag false positives, so expert review
   is mandatory, and **consistency ≠ correctness**: consistent artifacts can still
   describe the wrong system. `[AI4RE]` If input may be confidential (production code,
   regulated specs), remind the user not to paste it into external AI services.

## Use cases

### 1. Analyze Requirements Consistency `[AI4RE]`

Detect and classify relationships or issues between requirements in a specification.

1. Parse the input, normalize whitespace, identify requirement lines. Preserve existing
   IDs; generate `REQ-###` IDs for missing ones in reading order.
2. Compare all requirements pairwise using semantics, values, ranges, conditions, roles,
   versions, units, and implied dependencies. Include each pair once.
3. Classify each detected pair with category and subtype from the detection scope:
   Conflicts · Similarity/Duplication · Dependencies/Preconditions ·
   Complementary/Elaboration · Terminology inconsistencies · Version drift ·
   Inter-Requirement Test/Quality Misalignment · Completeness & Implied Gaps ·
   Functional vs Non-Functional Misalignment · other (named and justified).
4. Write a 2–3 sentence, pair-specific improvement suggestion per finding.
5. Group findings by relationship type; quote requirement text exactly; never list
   unrelated individual requirements. If nothing is found, say so in a single section.
6. For very large sets, run iteratively until re-runs surface no new issues; for
   multi-document input, add abstraction-level or trace attributes first (workflow
   step 2).

Template: *Analyze Requirements Consistency* in
[references/templates.md](references/templates.md).

### 2. Check Model Consistency `[AI4RE]`

Pairwise consistency check of two interconnected UML diagrams.

1. Identify the diagram type of each given diagram.
2. Parse each diagram; extract all model elements according to the UML metamodel
   (classes, attributes, operations with signatures, associations with multiplicities,
   actors, lifelines, messages, states, activities, constraints/notes).
3. For each class of UML elements, check for inconsistencies between the diagrams:
   similar but not identical wording for elements of the same class; not clearly
   defined stakeholder groups; inconsistent system boundaries; inconsistent states or
   activities. Also compare signatures/types, multiplicities vs. shown behavior, and
   lifecycle constraints vs. message order (as in the guide's worked example).
4. Report each finding with **exact element names from the input**, its impact, and a
   concrete suggestion (including the "if same concept … / if different concept …"
   branching the guide's example uses).
5. Close with a summary of key consistency fixes. The prompt is tailored to *two*
   diagrams — for more, run pairwise comparisons, ideally one fresh session each.

Template: *Check Model Consistency* in
[references/templates.md](references/templates.md).

### 3. Compare Specification With Source Code `[AI4RE]`

Identify discrepancies between documented specification and actual implementation.

1. Perform a semantic analysis of the requirements to extract relevant conditions,
   rules, and processes.
2. Analyze the source code to identify the logic actually implemented.
3. Compare and highlight any **missing, altered, or additional** behavior; assign each
   specification item a match status: Match / Partial / Missing / Extra.
4. Distinguish "not implemented" from "not visible in the provided files" — backend
   validation may exist outside the excerpt; mark such rows Partial with an explicit
   caveat, not Missing. `[AI4RE]` (pitfall: gaps related to context cannot be
   retrieved; NFRs such as safety/security may be unverifiable from code alone).
5. Suggest changes or additions to the specification *or* the code per discrepancy.
6. If code snippets map to multiple, hierarchically linked requirements, note that the
   flat table is insufficient and offer a hierarchical or matrix view. `[AI4RE]`

Template: *Compare Specification With Source Code* in
[references/templates.md](references/templates.md).

## Output formats

- **Consistency findings report:** sections grouped by relationship type (bold heading
  + horizontal rule), numbered pairs with `Related Requirements` (IDs + exact quoted
  text), `Type of Relationship / Issue: Category — Subtype`, `Improvement Suggestion`
  (2–3 sentences). Explicit "no issues detected" section when empty.
- **Model inconsistency list:** human-readable numbered findings, each citing exact
  element names, with Finding / Impact / Suggestion structure and a closing fix summary.
- **Discrepancy table:** columns `Specification Item | Code Reference | Match Status
  (Match / Partial / Missing / Extra) | Explanation`, followed by a summary and
  recommendations block.
- Plain markdown unless the user requests another format (e.g. CSV for tool import).

## Quality gates

Every findings report must satisfy `[AI4RE]`: each finding evidenced by exact quotes or
element names from the input; each pair categorized exactly once in its most appropriate
category; suggestions actionable and pair-specific; input text never altered.
`[Supplementary: ISO/IEC/IEEE 29148:2018]` The checks operationalize the *consistency*
characteristic (no conflicting content, uniform terminology, compatible values/units)
and support *verifiability* and *completeness*. Full operationalized checklists live in
[references/checklists.md](references/checklists.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open
questions:

- Evidence scan: every finding cites verbatim requirement text, exact element names, or
  a concrete code reference. Findings without traceable evidence are deleted.
- Duplication scan: no pair or element reported in more than one category.
- False-positive scan: are "duplicates" actually the same requirement at different
  abstraction levels? Is a "conflict" resolved by context elsewhere in the input?
- Coverage scan: state what was not checked (files not provided, NFRs unverifiable from
  code, diagrams beyond the compared pair, requirement ranges skipped due to size).
- Framing scan: report labeled a draft; consistency-≠-correctness caveat present;
  expert review recommended; iterative re-run suggested for large inputs.

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing any of the three use cases |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
