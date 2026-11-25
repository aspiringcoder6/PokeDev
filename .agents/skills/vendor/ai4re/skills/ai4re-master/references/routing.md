# Routing Table — AI4RE Master Consultant

> **Provenance:** `[AI4RE-adapted]` — taxonomy and use-case titles from the IREB AI4RE
> Prompt Guide; trigger phrases and precondition logic are supplementary
> `[Supplementary: this repository]`.

## Full routing table

| # | AI4RE use case | Cluster | IREB activity | Skill | Typical triggers |
|---|----------------|---------|---------------|-------|------------------|
| 1 | Introduce a New Domain | Explore | Elicitation | `elicitation-preparation` | "new to this domain", "explain the domain", onboarding |
| 2 | Identify Stakeholders | Explore | Elicitation | `elicitation-preparation` | "who are the stakeholders", stakeholder map/analysis |
| 3 | Prepare Interview | Explore | Elicitation | `elicitation-preparation` | "interview questions", interview guide |
| 4 | Plan Workshop | Explore | Elicitation | `elicitation-preparation` | "workshop agenda", facilitation plan |
| 5 | Refine Transcription | Transcribe | Elicitation | `elicitation-transcription` | raw interview/workshop transcript to clean up |
| 6 | Transcribe Whiteboard Images | Transcribe | Elicitation | `elicitation-transcription` | photo of whiteboard/flipchart to digitize |
| 7 | Identify Requirements | Extract | Elicitation | `requirements-extraction` | "find the requirements in…", mine notes/documents |
| 8 | Specify Requirement | Formulate | Documentation | `requirements-writing` | "formulate/rewrite this requirement", "as user story" |
| 9 | Decompose Requirement | Formulate | Documentation | `requirements-writing` | "break down", epic → stories, goal → sub-goals |
| 10 | Generate Synonym Table | Formulate | Documentation | `requirements-writing` | terminology inconsistent, synonym table |
| 11 | Generate Model From Text | Translate | Documentation | `requirements-translation` | "draw/model this as UML/BPMN/diagram" |
| 12 | Generate Text From Model | Translate | Documentation | `requirements-translation` | "describe this diagram in text" |
| 13 | Explain Requirements in Simple Language | Translate | Documentation | `requirements-translation` | "explain for non-technical stakeholders" |
| 14 | Generate Persona | Translate | Documentation | `requirements-translation` | "create a persona" |
| 15 | Generate Test Cases | Translate | Documentation | `requirements-translation` | "derive test cases / acceptance tests" |
| 16 | Generate Requirements From Source Code | Translate | Documentation | `requirements-translation` | legacy code, reverse engineering requirements |
| 17 | Generate Wireframe | Validate | Validation | `requirements-validation` | "wireframe/mockup to review with stakeholders" |
| 18 | Analyze Requirements Consistency | Verify | Validation | `requirements-verification` | "contradictions in the spec", consistency check |
| 19 | Check Model Consistency | Verify | Validation | `requirements-verification` | model vs. model / model vs. text alignment |
| 20 | Compare Specification With Source Code | Verify | Validation | `requirements-verification` | "does the code match the spec" |
| 21 | Analyze Change Request Impact | Align | Management | `change-impact-analysis` | "what does this change affect", CR assessment |
| 22 | Tag Requirements | Assign* | Management | `requirements-traceability` | classify/label requirements |
| 23 | Trace Requirements | Assign* | Management | `requirements-traceability` | trace matrix, link requirements to artifacts |

\* The guide spells this cluster "Asign" [sic]; this repository uses "Assign".

## Preconditions per skill

| Skill | Needs as input | If missing, run first |
|-------|----------------|----------------------|
| `elicitation-preparation` | project/domain context | — (start of chain) |
| `elicitation-transcription` | raw transcript or image | — |
| `requirements-extraction` | reasonably clean elicitation material | `elicitation-transcription` |
| `requirements-writing` | candidate requirement(s) or goal | `requirements-extraction` |
| `requirements-translation` | formulated requirements / model / code | `requirements-writing` |
| `requirements-validation` | formulated requirements (UI-related) | `requirements-writing` |
| `requirements-verification` | ≥ 2 artifacts, or one spec to check internally | `requirements-writing` / `requirements-translation` |
| `requirements-traceability` | a set of requirements (+ target artifacts for tracing) | `requirements-writing` |
| `change-impact-analysis` | change request + affected baseline (ideally trace links) | `requirements-traceability` |

## Disambiguation rules

- **"Validate" vs. "verify":** stakeholder-facing tangibility (wireframes, walkthroughs) →
  `requirements-validation`; artifact-internal consistency → `requirements-verification`.
- **"Extract" vs. "write":** finding candidates in material → `requirements-extraction`;
  polishing/formalizing known content → `requirements-writing`.
- **"Model" requests:** creating/converting models → `requirements-translation`; checking
  models → `requirements-verification`.
- **Glossary vs. synonym table:** synonym table (AI4RE) → `requirements-writing`; full
  glossary with definitions → `requirements-writing`, marked as supplementary extension.
- **Prioritization, effort estimation, requirements negotiation:** no AI4RE use case exists
  yet. Handle with general RE expertise, say explicitly that this is outside the AI4RE
  Prompt Guide's current scope, and apply the behavioral rules (draft, assumptions, open
  questions) anyway.
