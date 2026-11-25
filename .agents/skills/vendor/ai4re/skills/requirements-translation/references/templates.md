# Templates — Requirements Translation

> **Provenance:** `[AI4RE]` All templates below originate from the IREB AI4RE Prompt Guide,
> cluster *Translate* — pages
> [Generate Model From Text](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043418),
> [Generate Text From Model](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043398),
> [Explain Requirements in Simple Language](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043403),
> [Generate Persona](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043426),
> [Generate Test Cases](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043420),
> [Generate Requirements From Source Code](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2337669121).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[Supplementary: …]` are additions from other standards.

All templates follow the AI4RE configuration anatomy: **AI's role · My role · My purpose ·
Task · Format · Input**. Resolve every `[VARIABLE]` before use — either from the user's
request or by asking.

---

## 1. Generate Model From Text `[AI4RE]`

**Purpose:** Convert textual requirements, use cases or scenarios into a formal model in
importable textual notation.

```
AI's role: MBSE and modeling expert specializing in UML, BPMN, SysML v1 and SysML v2. You
can transform natural language requirements or use case descriptions into precise models,
ensuring compliance with modeling standards and providing clarity for stakeholders.
My role (user role): Requirements engineer who wants to generate models for [SYSTEM] to
ensure that stakeholders can quickly understand system information when expressed in
familiar modeling notations.
My purpose: Generating accurate, standards-aligned models (UML diagrams, BPMN processes,
SysML v1/v2 models) directly from text descriptions of requirements, use cases, or
scenarios, so stakeholders can interpret and validate them efficiently.

Task:
Use model language [MODELING_LANGUAGE] and diagram type [DIAGRAM_TYPE].
Use the input document and identify requirements who can be grouped together for a
representation in a diagram (consider the selected diagram type for this task).
Ask the user which group to start with.
After that continue using the selected group of requirements and identify all possible
relevant elements of the selected diagram type.
Interpret and refine ambiguities if needed.
Provide the output in textual notation (e.g., SysML v2 textual syntax, PlantUML, BPMN
XML), ensuring it can be imported into modeling tools.
Optionally, provide a simple visual diagram preview if appropriate.

Format:
Grouping of requirements - List the defined grouped requirements and explain why these can
be grouped together (max 3 sentences)
Diagram elements - List the identified diagram elements in a table format with explanation
for the different elements of the selected diagram type
Model Representation (main output) – Provide the model in textual notation (e.g., SysML v2
syntax, PlantUML code, BPMN XML).
Validation Note – Mention any assumptions made or gaps identified in the source text.

+ Add word file with requirements
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[SYSTEM]` | The system under consideration |
| `[MODELING_LANGUAGE]` | UML · BPMN · SysML v1 · SysML v2 |
| `[DIAGRAM_TYPE]` | Diagram type supported by the chosen modeling language |

`[Supplementary: Mermaid]` Mermaid is an equally importable textual notation and renders
natively in markdown toolchains (GitHub, GitLab, docs sites) — offer it alongside PlantUML
when the user has no modeling-tool constraint.

---

## 2. Generate Text From Model `[AI4RE]`

**Purpose:** Convert a model (UML, BPMN, SysML v1/v2 — image or textual notation) into
natural-language requirements, use cases or scenarios.

```
AI's role: MBSE and modeling expert specializing in UML, BPMN, SysML v1 and SysML v2. You
can extract information from models and transform them into natural language requirements
or use case descriptions.
My role (User Role): Requirements engineer who wants to generate text-based artifacts from
models for [SYSTEM] to ensure that stakeholders can quickly understand system information
when expressed in natural language.
My purpose: Generate text descriptions of requirements, use cases or scenarios from models
(UML diagrams, BPMN processes, SysML v1/v2 models), so that stakeholders can interpret and
validate them efficiently.

Task:
Use the input document and identify all possible relevant elements of the diagram in text.
Use the uploaded input to generate language based requirements based on the model.
Interpret and refine ambiguities if needed.

Format:
Use the following natural language requirement format: [FORMULATION]
Validation Note (optional) – Mention any assumptions made or gaps identified in the source
text.

+ Add an image from a diagram such as UML, BPMN, SysML v1, or SysML v2.
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[SYSTEM]` | The system under consideration |
| `[FORMULATION]` | user story · use case · IEEE · SOPHIST template · any other formulation standard |

**Practice from the guide's worked example** `[AI4RE-adapted]`: extract the model elements
into text first (actors, lifelines/components, functional scenarios, control structures
like `alt`/`opt`), then generate the requirements from that extraction — the two-step output
makes the translation traceable. Prefer machine-readable model input (textual notation)
over screenshots/PDFs; images without metadata invite omissions and hallucinations.

---

## 3a. Explain Requirements in Simple Language — Translate `[AI4RE]`

**Purpose:** Rephrase all requirements into a plain-language summary tailored to a specific
stakeholder group, item by item with an impact statement.

```
AI's role: Expert business analyst specializing in stakeholder communication
My role: Requirements engineer
My purpose: Bridging the gap between technical teams and business stakeholders by
translating complex requirements into simple, understandable language.

Task: Analyze the provided content and rephrase all of its requirements into a summary
tailored specifically for the target stakeholder [STAKEHOLDER_GROUP].
This summary should focus on the 'what' and the 'why' from their perspective, omitting
deep technical details about the 'how'.
Identify for the stakeholder group relevant requirements: First, thoroughly read the
document and extract all essential functional and non-functional requirements.
Focus on Impact: For each requirement, clearly state its benefit or impact on the target
stakeholder group. Answer the question, "Why should they care about this?"
Simplify and Rephrase: Translate each requirement into target group-specific language
Maintain Accuracy: Ensure that your simplified translation does not change, add, or remove
the core intent of the original requirements.

Format: Output in a clear, scannable format. Use a bulleted list. For each item, provide a
simple description and then a brief "What this means for you:" explanation.

+ Add requirements for analysis
```

| Variable | Meaning |
|----------|---------|
| `[STAKEHOLDER_GROUP]` | The group of stakeholders for which the requirements should be explained |

---

## 3b. Explain Requirements in Simple Language — Summary `[AI4RE]`

**Purpose:** Generate a thematic summary of existing requirements for a specific
stakeholder group.

```
AI's role: Expert business analyst specializing in stakeholder communication
My role: Requirements engineer
My purpose: Prepare stakeholder communication materials.

Task: Analyze the following requirements and create a summary tailored to the specified
stakeholder group. Adjust the level of detail, focus, and language based on the following
stakeholder [STAKEHOLDER_GROUP]. Group requirements into meaningful themes. Summarize by
theme, not by individual requirement.

Format: Deliver a structured summary aligned with the chosen stakeholder group's needs.

+ Add requirements for analysis
```

| Variable | Meaning |
|----------|---------|
| `[STAKEHOLDER_GROUP]` | The group of stakeholders for which the requirements should be explained |

**Mitigation add-ons from the guide's pitfall section** `[AI4RE]` — append when the risk
applies:
- "Where relevant, indicate potential limitations or implementation considerations."
- "Ensure key requirement intentions are preserved, even when summarized."
- "Do not list individual features — focus on grouped business impact."
- "Use language suitable for executive leadership — avoid operational or product-level
  details." (for executive audiences)

---

## 4. Generate Persona `[AI4RE]`

**Purpose:** Create one concise persona draft from stakeholder input (e.g. an interview
transcript) for refinement and stakeholder validation.

```
AI's role: experienced UX Designer specialized in creating user personas from stakeholder
interviews and domain-specific system insights
My role: requirements engineer
Purpose: Generate a persona of job/role [ROLE].

Task: Analyze the input and create a concise persona draft for the requirements engineer
to use for further refinement and stakeholder validation.
Use the following structure:
name (fictional)
age
job/role
main goals
day-to-day challenges
technology affinity
values or attitude towards change
specific expectations towards the system
Avoid stereotypes and clichés. Only use hypotheses if necessary and clearly label them for
later validation.
Only generate one persona, strictly based on the uploaded file.

Format: Plain text. Keep the text clear and under 200 words.

Image?: [IMAGE]
If image is 'yes': Generate a portrait of the persona that reflects the fictional
character. This should depict them in their natural working environment.

+ Add a file containing persona information, such as an interview transcription.
```

| Variable | Meaning |
|----------|---------|
| `[ROLE]` | Job or role of the persona |
| `[IMAGE]` | "yes" if an image of the persona should be generated, otherwise "no" |

---

## 5. Generate Test Cases `[AI4RE]`

**Purpose:** Derive structured test cases (positive, negative, edge) from requirements to
ensure each requirement is verifiable.

```
AI's role: Requirements analysis and software testing expert with expertise in parsing
technical documentation and generating test cases.
My role: Requirements engineer
My purpose: Generate corresponding test cases to ensure each requirement is verifiable.

Task: For each requirement, generate one or more test cases, including positive, negative,
and edge cases where applicable.

Format: Return the output in one table with the following columns: Test Case ID, ID of the
tested Requirement, Description, Input, Expected Output, Type (Positive/Negative/Edge)

+ Add requirements
```

This template has no configuration variables — attach the requirements as input.

**Practice from the guide** `[AI4RE-adapted]`: keep the source requirement IDs in the table
(traceability); for large requirement sets, divide the task into sub-tasks per feature or
module to avoid incomplete tables.

---

## 6. Generate Requirements From Source Code `[AI4RE]`

**Purpose:** Reverse-engineer a structured requirements specification from existing source
code.

```
AI's role: Specialist in software analysis and requirements engineering, responsible for
examining source code and extracting clear, structured, and unambiguous functional and
non-functional requirements
My role: Requirements engineer overseeing the reverse-engineering process to ensure the
resulting specification is accurate, complete, and suitable for further development. I
also need to understand the implemented logic in order to validate, maintain, and extend
the system.
My purpose: Generating a high-quality, reverse-engineered specification from existing
source code that can serve as a foundation for system evolution, maintenance, and
compliance.

Task: Analyze the provided source code to:
Identify and describe system functionalities, constraints, and dependencies.
Derive functional requirements (what the system does) and non-functional requirements
(performance, security, usability, etc.).
Ensure requirements are expressed in clear, testable, and implementation-independent
language.
Organize requirements logically (e.g., by feature, module, or priority).

Format: Structured specification document with the following sections:
Introduction – Brief context and assumptions.
Functional Requirements – Numbered list, each with a short title and detailed description.
Non-Functional Requirements – Grouped by category (e.g., performance, security).
Glossary – Definitions of key terms or domain-specific concepts.
Traceability Note – Indicate which parts of the code informed each requirement.

+ Add source code bundle
```

This template has no configuration variables — attach the source code bundle as input.

**Practice from the guide's pitfall section** `[AI4RE-adapted]`: prefer complete modules
over snippets; when only snippets are available, state explicitly which inferences are
limited by missing invocation context, and mark scope-exceeding requirements as
assumptions.

**NFR categories** `[Supplementary: ISO/IEC 25010:2023]`: group *Non-Functional
Requirements* by the ISO/IEC 25010:2023 characteristics plus *Randbedingungen* (ReqPOOL
convention, not ISO). Name the sub-characteristic per requirement; list categories without
code evidence as gaps rather than inventing content. Keep in sync with
`requirements-writing/references/nfr-quality-model.md`.

| # | Category (DE / EN) | Sub-characteristics |
|---|--------------------|---------------------|
| 1 | Funktionale Eignung / Functional Suitability | Funktionale Vollständigkeit, Funktionale Korrektheit |
| 2 | Leistungseffizienz / Performance Efficiency | Zeitverhalten, Ressourcenverbrauch, Kapazität |
| 3 | Kompatibilität / Compatibility | Koexistenz, Interoperabilität |
| 4 | Interaktionsfähigkeit / Interaction Capability | Erlernbarkeit, Bedienbarkeit, Schutz vor Benutzerfehlern, Nutzerbindung, Inklusivität (Barrierefreiheit), Benutzerunterstützung, Selbstbeschreibungsfähigkeit |
| 5 | Zuverlässigkeit / Reliability | Fehlerfreiheit, Verfügbarkeit, Fehlertoleranz, Wiederherstellbarkeit |
| 6 | Sicherheit / Security | Vertraulichkeit, Integrität, Nachweisbarkeit, Authentizität, Widerstandsfähigkeit |
| 7 | Wartbarkeit / Maintainability | Modularität, Wiederverwendbarkeit, Analysierbarkeit, Änderbarkeit, Testbarkeit |
| 8 | Flexibilität / Flexibility | Anpassbarkeit, Skalierbarkeit, Installierbarkeit, Austauschbarkeit |
| 9 | Betriebssicherheit / Safety | Betriebliche Einschränkungen, Risikoidentifikation, Fail-Safe-Verhalten, Gefahrenwarnung, Sichere Integration |
| 10 | Randbedingungen / Constraints *(not ISO 25010)* | Produkt- & Prozessrandbedingungen: Support, vertragliche und organisatorische Vorgaben |

The same grouping applies when use case 2 (*Translate to Stakeholder Language*) extracts
non-functional requirements from a document.
