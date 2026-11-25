# Templates — Requirements Traceability

> **Provenance:** `[AI4RE]` Both templates below originate from the IREB AI4RE Prompt Guide,
> cluster *Assign* — pages [Tag Requirements](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2430369836)
> and [Trace Requirements](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2430533633);
> cluster overview page [Assign](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2667839527)
> (titled "Asign" [sic] in the original guide). Wording is preserved; formatting is adapted
> for skill use. Sections marked `[Supplementary: …]` are additions from other standards.

Both templates follow the AI4RE configuration anatomy: **AI's role · Context · Task ·
Format · Input**. Resolve every `[VARIABLE]` before use — either from the user's request or
by asking.

---

## 1. Tag Requirements `[AI4RE]`

**Purpose:** Classify each requirement into exactly one category of a defined taxonomy —
consistent, explainable and reproducible.

```
AI's role: AI assistant who classifies software requirements into exactly one category
Context: consistent, explainable, and reproducible classification

Each requirement contains:
- ID: unique identifier for the requirement
- Text: detailed description of the requirement

Categories:
[CATEGORIES]

Decision rules:
- A category matches if at least one include criterion clearly applies.
- If exactly one category matches → select it.
- If multiple categories match → select the category that represents the primary goal of
  the requirement.
- If the primary goal cannot be determined → Category = UNCLEAR.

Reasoning rules:
- Cite the include criterion that triggered the primary category.
- If more than one category matches, explicitly state the secondary matching category in
  the reasoning.
- If UNCLEAR, explain:
  - why the intent is ambiguous
  - what information is missing to classify it confidently

Output format:
[OUTPUT FORMAT]

+ Add requirements.
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[CATEGORIES]` | A list of categories, such as the type of requirements (functional or non-functional). Each category has an ID, name, purpose description, and criteria description. |
| `[OUTPUT FORMAT]` | Excel · CSV · markdown table |

**Practice from the guide's worked example** `[AI4RE-adapted]`: define each category as
`ID – Name`, `Purpose:` one line, `Include criteria:` explicit list (this is what the
decision rules bind to); open the answer with a legend of the categories; per requirement
output `Category`, `Reasoning`, `Criterion` (quoted) and `Secondary match` where applicable;
state explicitly when no `UNCLEAR` classifications were necessary.

### Default NFR taxonomy — ISO/IEC 25010:2023 `[Supplementary: ISO/IEC 25010:2023]`

When the user asks to classify non-functional requirements but supplies no taxonomy, propose
this set as `[CATEGORIES]` and get confirmation. Category 10 is a ReqPOOL convention (not part
of ISO/IEC 25010). Keep in sync with `requirements-writing/references/nfr-quality-model.md`.

```
Q01 – Funktionale Eignung (Functional Suitability)
  Purpose: Completeness and correctness of the provided functions.
  Include criteria: Funktionale Vollständigkeit, Funktionale Korrektheit
Q02 – Leistungseffizienz (Performance Efficiency)
  Purpose: Performance relative to the resources used.
  Include criteria: Zeitverhalten, Ressourcenverbrauch, Kapazität
Q03 – Kompatibilität (Compatibility)
  Purpose: Working alongside and exchanging data with other systems.
  Include criteria: Koexistenz, Interoperabilität
Q04 – Interaktionsfähigkeit (Interaction Capability)
  Purpose: Interaction by the intended users, including people with disabilities.
  Include criteria: Erlernbarkeit, Bedienbarkeit, Schutz vor Benutzerfehlern,
  Nutzerbindung, Inklusivität (Barrierefreiheit, WCAG, EN 301 549),
  Benutzerunterstützung, Selbstbeschreibungsfähigkeit
Q05 – Zuverlässigkeit (Reliability)
  Purpose: Performing as specified over time and under faults.
  Include criteria: Fehlerfreiheit, Verfügbarkeit, Fehlertoleranz, Wiederherstellbarkeit
Q06 – Sicherheit (Security)
  Purpose: Protection of information and data against unauthorized access.
  Include criteria: Vertraulichkeit, Integrität, Nachweisbarkeit, Authentizität,
  Widerstandsfähigkeit
Q07 – Wartbarkeit (Maintainability)
  Purpose: Effective and efficient modification of the product.
  Include criteria: Modularität, Wiederverwendbarkeit, Analysierbarkeit, Änderbarkeit,
  Testbarkeit
Q08 – Flexibilität (Flexibility)
  Purpose: Adaptation to changed requirements, contexts and environments.
  Include criteria: Anpassbarkeit, Skalierbarkeit, Installierbarkeit, Austauschbarkeit
Q09 – Betriebssicherheit (Safety)
  Purpose: Avoiding danger to people, property or the environment.
  Include criteria: Betriebliche Einschränkungen, Risikoidentifikation,
  Fail-Safe-Verhalten, Gefahrenwarnung, Sichere Integration
Q10 – Randbedingungen (Constraints; not part of ISO/IEC 25010)
  Purpose: Product and process constraints outside the product quality model.
  Include criteria: Support, vertragliche Vorgaben (SLA, Lieferformate, Nachweise),
  organisatorische Vorgaben (Personal, Sprache, Prozesse)
```

Disambiguation rules: product accessibility → Q04; accessibility *proof obligations*
(test report, accessibility statement, contact person) → Q10. A statement that describes
what the system does belongs to the functional requirements, not Q01.

---

## 2. Trace Requirements `[AI4RE]`

**Purpose:** Establish bidirectional trace links between one requirement and a set of
provided artifacts, with exact evidence locations.

```
AI's role: Requirements engineer
Context: Automatically mapping requirements to their related artifacts to enable
traceability.

Task: Screen the added artefacts. Identify the (a) source of the requirement mentioned
below and (b) downstream artefacts such as design models, code modules, test cases, and
validation results related to the requirement. Show me its exact location within the added
artefacts.

- Base your answer strictly on the actual content of the artefacts, not on file names.
- When referencing an artefact, identify the document title and author(s) from the first
  page, if available and meaningful.
- Specify the exact location (page, section, slide, or paragraph) and provide a direct
  quote or summary.
- If the requirement is not found or only partially addressed, state this explicitly.
- Classify the reference as "pre" for pre-requirements specification traceability (source)
  and "post" for post-requirements specification traceability (downstream artefacts).

Requirement:
[REQUIREMENT]

+ Add artefacts.
```

| Variable | Meaning |
|----------|---------|
| `[REQUIREMENT]` | Requirement to be traced. |

**Practice from the guide's worked example** `[AI4RE-adapted]`: lead with a short summary
(what is traceable pre, what post, what is missing); structure the body as *A) Source
Artefacts ("pre")* and *B) Downstream Artefacts ("post")*, each entry with document,
location, direct quote and acceptance criteria covered; mark indirectly related artifacts
as such instead of forcing a link; add *Not Found in Provided Artefacts*, a *Coverage of
Acceptance Criteria* table, *Gaps / Issues Identified* and a *Recommendation* (links to
record in the RM tool, variance log, Definition-of-Done additions, validation planning).

**Synonym-aware search** `[AI4RE]` (from Pitfalls): the AI may focus on literal word
matches, producing false negatives when artifacts use synonyms — explicitly search for
synonyms of the requirement's key terms (see the *Generate Synonym Table* use case in
`requirements-writing`).

---

## Supplementary terminology `[Supplementary: Gotel & Finkelstein 1994, IREB CPRE Glossary]`

- **Pre-RS traceability ("pre"):** links from a requirement back to its origins — needs,
  stakeholder statements, elicitation artifacts, contracts.
- **Post-RS traceability ("post"):** links from a requirement forward to artifacts that
  refine, realize or verify it — design, code, tests, validation results.
- **Bidirectional traceability** `[Supplementary: ISO/IEC/IEEE 29148:2018]`: both directions
  must be maintainable; a requirement without an identifiable source or without downstream
  coverage is a traceability gap, not a formatting detail.
