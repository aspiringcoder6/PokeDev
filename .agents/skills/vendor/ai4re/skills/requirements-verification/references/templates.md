# Templates — Requirements Verification

> **Provenance:** `[AI4RE]` All templates below originate from the IREB AI4RE Prompt Guide,
> cluster [Verify](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2667413518) —
> pages [Analyze Requirements Consistency](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2571173889),
> [Check Model Consistency](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2585985025),
> [Compare Specification With Source Code](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2556493825).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[AI4RE-adapted]` or `[Supplementary: …]` are restructured or additional content.

All templates follow the AI4RE configuration anatomy: **AI's role · My role/Context ·
Purpose · Task · Format · Input**. Resolve every `[VARIABLE]` before use — either from
the user's request or by asking. The `+ Add …` line marks where the input artifacts are
appended.

---

## 1. Analyze Requirements Consistency `[AI4RE]`

**Purpose:** Detect conflicts, redundancies, dependency gaps and terminology
inconsistencies across a list of requirements and produce a categorized findings report.

```
AI's role: Expert in requirements engineering and analysis
Context: Creating coherent and well-organised specifications
Task: Review a provided list of requirements, detect and classify relationships or
issues between them and produce a rich text output grouped by relationship type.

Instructions:
- Compare all requirements pairwise to detect relationships or issues.
- Include each pair once.
- Classify the relationship precisely, using a category and a subtype where applicable.
- Provide concise, actionable improvement suggestions (2–3 sentences) tailored to the
  specific pair.
- Organize detected pairs into sections grouped by relationship type, separated with
  bold headings and horizontal rules.

Detection scope (categories and common subtypes):
- Conflicts: direct contradiction; numeric/value or range conflict; unit mismatch;
  conditional conflict; temporal/sequence conflict; actor/scope conflict;
  priority/modality conflict.
- Similarity/Duplication: exact duplicate; near-duplicate; partial overlap;
  general–specific.
- Dependencies/Preconditions: precondition; sequence/order; trigger/event;
  interface/protocol dependency.
- Complementary/Elaboration relationships: elaboration of acceptance criteria;
  detailed specification complements a higher-level requirement.
- Terminology inconsistencies: terminology mismatch; unit mismatch; actor/role
  mismatch; tense/modality mismatch.
- Version drift: version conflict; outdated vs current references.
- Inter-Requirement Test/Quality Misalignment: acceptance criteria contradiction;
  conflicting measurable thresholds; testability clash caused by combination;
  verification impossibility between paired requirements.
- Any other meaningful inferred relationship type: clearly name and justify the
  category.
- Completeness & Implied Gaps: two or more requirements together reveal a missing
  companion requirement or coverage hole; implied but absent requirements.
- Functional vs Non-Functional Misalignment: NFR contradicting functionality.
- Implied-Gap Conflicts Between Existing Requirements: two or more requirements
  together reveal a missing companion requirement or coverage hole.

Output format (rich text table):
Group results by relationship type. Each group starts with a bold heading and a
horizontal rule. Under each heading, list each detected pair as a numbered item with
the following structure:
  Related Requirements
  — [ID-1]: "[Full text of requirement 1]"
  — [ID-2]: "[Full text of requirement 2]"
  Type of Relationship / Issue: [Category] — [Subtype]
  Improvement Suggestion: [2–3 sentences explaining how to resolve the issue and why
  it matters.]
Separate each group with a horizontal rule. If no related pairs are found, output a
single section noting that no issues were detected.

Pairing and content rules:
- Do not list individual, unrelated requirements.
- Do not repeat the same pair in multiple sections; choose the most appropriate
  category.
- Do not alter requirement text; quote it exactly.

Execution steps (do not include in the output):
- Parse the input, normalize whitespace, and identify requirement lines.
- Preserve existing IDs; generate REQ-### IDs for missing ones in reading order.
- Perform pairwise comparison to detect relationships using semantics, values, ranges,
  conditions, roles, versions, units, and implied dependencies.
- Classify each detected pair and draft tailored improvement suggestions.
- Group, sort, and render the final output as specified, with clear headings and
  separators.

+ Add list of requirements
```

| Variable / input | Meaning |
|------------------|---------|
| `+ Add list of requirements` | The requirements to be analyzed, appended to the prompt (with IDs where available) |

**Multi-document usage** `[AI4RE]`: the prompt can be applied to multiple documents at
once to find cross-document discrepancies. Decomposed requirements (system vs. component
level) are legitimately similar at different abstraction levels — to avoid false
duplicates, either (1) add dedicated attributes per requirement for *Level of
Abstraction*, *document name*, or *trace references* (e.g. `Traced to: Sys-Req-1`), or
(2) encode the abstraction level in the requirement ID itself (e.g. `Sys-Req-1` vs.
`Comp-Req-1`).

**Accuracy at scale** `[AI4RE]`: large requirement sets (e.g. over 5,000 requirements)
can trigger "lost in the middle" attention issues. Run the check iteratively —
re-run until the documentation achieves consistency.

---

## 2. Check Model Consistency `[AI4RE]`

**Purpose:** Check consistency between two interconnected UML diagrams and suggest
improvements. Tailored specifically to UML and the pairwise comparison of two diagrams;
for more diagrams, run pairwise iterations.

```
AI's Role: You are an MBSE and modeling expert specializing in UML
My Role: Requirements engineer who wants to check consistency between multiple related
models regarding [SYSTEM]
Purpose: Checking consistency between different diagrams. For this purpose you are
given two UML diagrams (e.g., class diagrams, sequence diagrams, activity diagrams,
state machine diagrams)

Task:
- Identification of diagram types: Identify the diagram type for each given diagram
- Parsing and Extraction of Model Elements: Parse each UML diagram. Identify all model
  elements according to the UML metamodel
- Check for inconsistencies: For each class of UML elements, check if there are
  inconsistencies between the diagrams. Inconsistencies may include:
  - similar but not identical wording for elements of the same class
  - not clearly defined stakeholder groups
  - inconsistent system boundaries
  - inconsistent states, activities

Format:
List all identified inconsistencies in a human readable format and make specific
suggestions for improvement to ensure consistency.
Only report findings that cite exact element names from the input.

+ Add diagrams as an image or as a code-based artifacts, f.e. PlantUML, Mermaid
```

| Variable / input | Meaning |
|------------------|---------|
| `[SYSTEM]` | System under consideration |
| `+ Add diagrams …` | Exactly two interconnected UML diagrams, as images or code-based artifacts (PlantUML, Mermaid) |

**Practice from the guide's worked example** `[AI4RE-adapted]`: structure the answer as
(1) diagram types, (2) parsed model elements per diagram, (3) findings grouped by
concern (naming/conceptual alignment, operation signatures and datatypes, multiplicity
vs. dynamic behavior, lifecycle and states, stakeholders and system boundary) — each
with *Finding / Impact / Suggestion*, where suggestions offer explicit alternatives
("if same concept, rename …; if different concept, add …"), (4) summary of key
consistency fixes.

---

## 3. Compare Specification With Source Code `[AI4RE]`

**Purpose:** Identify discrepancies between the documented specification and the actual
implementation in the source code.

```
AI's role: expert in code analysis and software requirements validation
My role: requirements engineer.
My Purpose: Identify discrepancies between the documented specification and the actual
implementation in the source code.

Task: Perform a semantic analysis of the requirements to extract relevant conditions,
rules, and processes. Then, analyze the source code using pattern recognition to
identify the logic actually implemented. Compare the extracted requirements with the
implemented logic and highlight any missing, altered, or additional behavior. If gaps
or inconsistencies are discovered, generate suggestions for changes or additions to
the specification or the code.

Output format: table with columns for: Specification Item, Code Reference, Match
Status (Match / Partial / Missing / Extra), and Explanation.

+ Add files to compare
```

| Variable / input | Meaning |
|------------------|---------|
| `+ Add files to compare` | The requirements specification and the source code files under comparison |

**Practice from the guide's worked example** `[AI4RE-adapted]`: reference concrete code
locations in *Code Reference* (file plus element, e.g. `app.js –
if (familyMembers.length > 5)`); close with a *Summary & Recommendations* block that
buckets requirements into Good Matches / Partially Fulfilled / Missing Implementations.
When code cannot confirm a rule (e.g. backend validation not in the provided files),
mark it *Partial* with an explicit caveat rather than *Missing*. If code snippets map to
multiple hierarchically linked requirements, note that the flat table is insufficient
and offer a hierarchical or matrix view instead `[AI4RE]`.
