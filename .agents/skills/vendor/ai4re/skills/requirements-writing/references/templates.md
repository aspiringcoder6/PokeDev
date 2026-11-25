# Templates — Requirements Writing

> **Provenance:** `[AI4RE]` All templates below originate from the IREB AI4RE Prompt Guide,
> cluster *Formulate* — pages [Specify Requirement](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043416),
> [Decompose Requirement](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043400),
> [Generate Synonym Table](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043405).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[Supplementary: …]` are additions from other standards.

All templates follow the AI4RE configuration anatomy: **AI's role · My role · My purpose ·
Task · Format · Input**. Resolve every `[VARIABLE]` before use — either from the user's
request or by asking.

---

## 1. Specify Requirement `[AI4RE]`

**Purpose:** Reformulate one requirement in an appropriate standard and validate it against
a quality standard.

```
AI's role: Requirements specification expert
My role: Requirements engineer
My purpose: Requirement formulated in an optimized way to increase readability and
comprehensibility.

Task: Optimize the formulation of the following requirement.
Formulation standard: [FORMULATION]
Quality standard: [QUALITY]

Step 1: If the formulation standard is "none," identify the standard used for the input
requirement (e.g., use case, user story incl. acceptance criteria, IEEE, SOPHIST template).
If a standard is found, use it for further proceedings.
Step 2a: If the formulation standard is still "none", select the most appropriate standard,
such as use case or user story, and use it.
Step 2b: Otherwise, if a formulation standard has been identified, determine if there are
more appropriate formulation standards for this requirement. If so, stop proceeding and
suggest one or two alternatives. Then, ask which formulation standard should be used.
Proceed once the formulation standard has been given. The provided standard may be the one
originally entered.
Step 3: Formulate the requirement according to the chosen standard.
Step 4: Validate the requirement according to the quality standard. If the requirement does
not meet any quality criteria, request missing information and repeat step 3.

Format: [FORMAT]
Input: [REQUIREMENT]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[FORMULATION]` | `none` (AI selects) · user story incl. acceptance criteria · use case · IEEE · SOPHIST template · any other standard |
| `[QUALITY]` | INVEST Criteria · ISO/IEC/IEEE 29148:2018 · INCOSE · IREB CPRE |
| `[FORMAT]` | e.g. "plain text; only output the requirements." |
| `[REQUIREMENT]` | The requirement to be specified |

---

## 2. Decompose Requirement — into system requirements `[AI4RE]`

**Purpose:** Break a high-level requirement down into detailed, quality-conformant system
requirements.

```
AI's role: Domain expert in [DOMAIN] with extensive experience in both its technical
foundations and practical applications
My role: Requirements engineer of a [SYSTEM]
My purpose: Write high quality system requirements that meet the quality criteria [QUALITY].

Task: Break down the following high-level requirement into detailed system requirements
that follow the defined quality criteria:
[REQUIREMENT]

Format: List of system requirements written in clear, actionable language suitable for a
software specification: [FORMULATION]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[DOMAIN]` | The domain under consideration |
| `[SYSTEM]` | The system under consideration |
| `[QUALITY]` | INVEST Criteria · ISO/IEC/IEEE 29148:2018 · INCOSE · IREB CPRE |
| `[REQUIREMENT]` | Requirement that should be broken down |
| `[FORMULATION]` | user story incl. acceptance criteria · use case · IEEE · SOPHIST template · other |

**Practice from the guide's worked example** `[AI4RE-adapted]`: open the answer with an
*Assumptions & Scope* block; include non-functional requirements grouped by ISO/IEC
25010:2023 category plus *Randbedingungen* ([nfr-quality-model.md](nfr-quality-model.md));
close with *Risks / Points to Clarify* and an MVP *Recommendation*. Every requirement is
self-contained — no references to other requirements in the text.

---

## 3. Decompose Requirement — main goals into sub-goals `[AI4RE]`

**Purpose:** Break a high-level goal into SMART sub-goals.

```
AI's role: Domain expert in [DOMAIN] with extensive experience in both its technical
foundations and practical applications
My role: Requirements engineer of a [SYSTEM]
My purpose: Write high quality goals that meet the SMART quality criteria (Specific,
Measurable, Achievable, Relevant, Time-bound).

Task: Break down the following high-level goal into appropriate sub-goals:
[GOAL]

Format: List of SMART goals for a solution.
```

| Variable | Meaning |
|----------|---------|
| `[GOAL]` | High-level goal that should be broken down |

---

## 4. Generate Synonym Table `[AI4RE]`

**Purpose:** Create a terminology alignment table from a requirements specification.

```
AI's role: Expert in requirements engineering and in [SYSTEM/DOMAIN]
My role: Requirements engineer
My purpose: Creating a synonym table to improve the quality of the requirements
specification. A synonym table lists key terms used in the document along with their
synonyms, abbreviations, or alternative expressions. It helps readers understand that
different terms may refer to the same concept.

Task: Read the requirements specification provided. Create a synonym table as follows:

Identify key terms
- Go through your document and highlight technical terms, acronyms, and domain-specific
  language.
- Focus on terms that may have multiple names or are used inconsistently.
- Avoid overloading the table with trivial synonyms.

Collect synonyms and variants
- For each term list: synonyms (e.g., "server" and "host"), abbreviations (e.g., "CPU" for
  "Central Processing Unit"), alternative spellings or regional variants (e.g., "color" vs.
  "colour").
- To include a primary term in the table, it must be used in the requirements
  specification. To include a synonym or variant in the table, it must be used in the
  requirements specification. Add any long forms of abbreviations used in the requirements
  specification, even if the long form is not used in the requirements specification.

Format:
Output the table in markdown.
Column 1: "Primary Term" · Column 2: "Synonyms / Variants" · Column 3: "Notes"
Arrange the primary terms in alphabetical order.

+ Add requirements specification
```

| Variable | Meaning |
|----------|---------|
| `[SYSTEM/DOMAIN]` | System or domain under consideration |

---

## Supplementary formulation standards `[Supplementary]`

Quick reference for standards the templates may negotiate:

- **User story:** `As a <role>, I want <capability>, so that <benefit>` + acceptance
  criteria (Given/When/Then). Quality: INVEST.
- **EARS** `[Supplementary: EARS — Mavin et al.]`: `While <state>, when <trigger>, the
  <system> shall <response>` (ubiquitous / event-driven / state-driven / unwanted-behavior /
  optional-feature variants).
- **ISO/IEC/IEEE 29148** `[Supplementary]`: `The <system> shall <action> <object>
  <qualifier/measure>` — one requirement per statement, measurable qualifiers.
- **SOPHIST template**: German-language RE sentence template ("Das System muss …") with
  process verb, object and legal obligation term (muss/soll/kann).
