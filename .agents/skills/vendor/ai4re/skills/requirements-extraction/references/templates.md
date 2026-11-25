# Templates — Requirements Extraction

> **Provenance:** `[AI4RE]` The template below originates from the IREB AI4RE Prompt Guide,
> cluster *Extract* — pages [Extract](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2667675657)
> and [Identify Requirements](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2315780460).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[AI4RE-adapted]` or `[Supplementary: …]` are restructured or additional content.

The template follows the AI4RE configuration anatomy: **AI's role · My role · Purpose ·
Task · Format · Input**. Resolve every `[VARIABLE]` before use — either from the user's
request or by asking.

---

## 1. Identify Requirements `[AI4RE]`

**Purpose:** Analyze stakeholder input and identify the relevant requirements, each with a
traceable reference to the input.

```
AI's role: Expert in requirements engineering
My role: Requirements engineer
Purpose: Identify the relevant requirements from stakeholder input.

Task: Analyze the given stakeholder input and identify the relevant requirements.

Format: Table with two columns:
column 1 'Requirement': [Write a clear, concise statement, ideally using the user story
template: "As a [role], I want [feature], so that [benefit]"]
column 2 'Reference': [Quote the input for this requirement]

+ Add stakeholder input
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| Stakeholder input (appended) | The elicitation material to analyze: interview transcript, workshop notes, emails, meeting minutes, documents |
| `[role]`, `[feature]`, `[benefit]` | Output placeholders of the user story template — filled per extracted requirement by the AI, not configured by the user |

**Practices from the guide's worked example** `[AI4RE-adapted]`: open with a one-line
summary of what the table contains and how traceability works; after the table, close with
a *Recommendation* block — (1) validate the candidates with subject matter experts and
assign priorities (e.g., MoSCoW method), (2) refine key candidates with acceptance criteria
and measurable KPIs, (3) check for organization-specific context (e.g., systems in use)
that should be added as non-functional requirements; offer follow-ups such as a prioritized
backlog with acceptance criteria or a functional vs. non-functional mapping.

---

## 2. Identify Requirements — extended extraction table `[AI4RE-adapted]`

**Purpose:** Same extraction, but with the classification and grouping the guide's RE task
description calls for ("Structuring this information into functional requirements, quality
requirements, and constraints, and grouping them by feature or topic"). Use when the user
wants a structured intake for a backlog or specification skeleton.

```
AI's role: Expert in requirements engineering and in [DOMAIN]
My role: Requirements engineer of a [SYSTEM]
Purpose: Identify the relevant requirements from stakeholder input, classify and group
them, and surface gaps and interdependencies.

Task: Analyze the given stakeholder input and identify the relevant requirements.
Classify each requirement as functional requirement, quality requirement, or constraint;
if a requirement spans categories, say so instead of forcing one category. Group the
requirements by feature or topic. After the table, list: (a) interdependencies between
requirements, (b) gaps — requirement types or topics the input does not cover, unanswered
questions, contradictions.

Format: Table with six columns:
column 1 'ID'
column 2 'Requirement': [Write a clear, concise statement, ideally using the user story
template: "As a [role], I want [feature], so that [benefit]"]
column 3 'Reference': [Quote the input for this requirement]
column 4 'Type': [functional / quality / constraint — or combination, flagged]
column 5 'Topic': [feature or topic group]
column 6 'Notes': [assumptions, uncertain interpretations, duplicates merged]

+ Add stakeholder input
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[DOMAIN]` | The domain under consideration |
| `[SYSTEM]` | The system under consideration |
| Stakeholder input (appended) | The elicitation material to analyze |

---

## Formulation note `[AI4RE]`

The guide's pitfall *Reliance on User Story Template* applies to both templates: user
stories are helpful, but they may not be sufficient for complex technical or regulatory
requirements that need more detailed specification. Extract such candidates as plain
declarative statements and hand them to `requirements-writing` for proper specification.
