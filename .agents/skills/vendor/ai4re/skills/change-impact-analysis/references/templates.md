# Templates — Change Impact Analysis

> **Provenance:** `[AI4RE]` The template below originates from the IREB AI4RE Prompt Guide,
> cluster *Align* — page [Analyze Change Request Impact](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2430369793).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[Supplementary: …]` or `[AI4RE-adapted]` are additions.

The template follows the AI4RE configuration anatomy of this page: **AI's role · Context ·
Task · Format · Input (attached artifacts)**. Resolve every `[VARIABLE]` before use —
either from the user's request or by asking.

---

## 1. Analyze Change Request Impact `[AI4RE]`

**Purpose:** Identify and evaluate all impacts of a change request on requirements and
related documentation, so that necessary actions can be planned and communicated,
inconsistencies prevented, and requirements kept up to date.

```
AI's role: Specialist in impact analysis for requirements and associated documentation.
Your responsibility is to analyze the described change request and identify all affected
requirements, related documentation elements, and - if known - impacted modules, systems,
or interfaces.

Context: You support a requirements engineer who is responsible for managing the change
process and coordinate updates across requirements, system documentation, and design
artifacts. You determine the type of impact and propose suitable actions or adaptations.
The goal is to identify and evaluate all impacts of a change request on requirements and
related documentation, so that the requirements engineer can plan and communicate
necessary actions, prevent inconsistencies, and maintain up-to-date requirements. When you
propose actions show me the exact location where I should change the artefacts.

Task:
Change request:
[CHANGE REQUEST]

Screen the provided change request description and its context (e.g., related
requirements, business concepts, UI mockups, process or UML diagrams).

Identify the change request elements and the affected requirements.

For each affected requirement, determine the associated documentation artifacts that need
to be updated

Propose actions or adaptations to maintain consistency and correctness within the
artifacts, show me the exact location where I should change the artefacts, and name the
responsible persons or departments (if known).

Highlight risks, dependencies, or validation needs.

Also suggest missing artifacts.

Format:
Present results in a clear, structured, and readable format. Use a structured table where
each change request element can relate to multiple affected requirements and actions.

Columns:
- Impacted Requirement / Artifact
- Source
- Type of Impact
- Proposed Action
- Dependencies / Risks
- Comments

Modules, systems, and interfaces should be listed according to the corresponding artifact.
Name the source so that I can see what type of information you are referring to (for
example: missing artifacts, given input, connected systems, or similar). When you use or
refer to certain sources, use the exact file name or path so that I can identify them.

+ Add artefacts to be analyzed
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[CHANGE REQUEST]` | The change request under consideration |
| *(attached artifacts)* | The artifacts to be analyzed: requirements lists, use case descriptions, business concepts, UI mockups/GUI prototypes, process diagrams, UML/class diagrams, interface specifications — attached with their exact file names |

**Practices from the guide's worked example** `[AI4RE-adapted]`: open the answer with the
list of **change request elements identified** (the CR decomposed into atomic changes);
after the impact table, add **"Additional actions and exact edit points (by document)"**,
**suggested responsibilities** per action stream, **risks, dependencies and validation
needs**, **suggested missing/updated artifacts** (with proposed owners), and a
**validation checklist before release**. Cite each statement's source documents (e.g.
`[doc1]`, `[missing artifacts]`, `[given input]`) and resolve the citation keys to exact
file names at the end.

---

## Recommended supplementary inputs `[AI4RE]` (from Pitfalls & Tips mitigations)

Request these alongside the artifacts to be analyzed — each one closes a known failure
mode of AI-based impact analysis:

| Input | Closes which pitfall |
|-------|----------------------|
| Traceability matrix, architecture diagrams, system boundary definitions | Overlooking hidden dependencies |
| Glossary with definitions; business rule document | Misinterpreting business rules in text |
| Interface descriptions, class diagrams, service specifications | Confusing logical vs. structural impacts |
| Fixed abstraction levels for post-processing categorization | Inconsistent granularity of impacts |
