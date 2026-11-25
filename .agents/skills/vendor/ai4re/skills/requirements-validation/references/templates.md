# Templates — Requirements Validation

> **Provenance:** `[AI4RE]` The template below originates from the IREB AI4RE Prompt Guide,
> cluster *Validate* — page
> [Generate Wireframe](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2598010883).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[Supplementary: …]` are additions from other sources.

The template follows the AI4RE configuration anatomy: **AI's role · My role · My purpose ·
Task · Rules · Input · Output**. Resolve every `[VARIABLE]` before use — either from the
user's request or by asking.

---

## 1. Generate Wireframe `[AI4RE]`

**Purpose:** Generate mid-fidelity UI artifacts from requirements, using UI specifications
as structural guidance, to make requirements tangible and reviewable for stakeholder
validation.

```
AI's role: Expert in Requirements Engineering with expertise in UI/UX
My role: Requirements Engineer
My purpose: Validation of requirements with stakeholders with the help of wireframes

Task: Create mid-fidelity wireframes for:
system: [SYSTEM]
domain: [DOMAIN]
target group: [TARGET GROUP]
type of application: [APPLICATION TYPE]

Obligatory rules [delete the optional ones ID3 to 6 if not needed]:
1. Derivation: Derive all screens and features strictly from the chosen input; do not add
   anything not explicitly supported.
2. Navigation rule: Only include navigation elements that are explicitly supported by the
   chosen input (no invented dashboards/menus/quicklinks).
3. States: For every top-level screen you derive, include empty, loading, and error states.
   Mark them with a light yellow background.
4. Traceability: Display a small red tag next to each UI element derived from the input
   (e.g., "Ref: US-1"). Don't display it elsewhere.
5. Assumptions: If something is unspecified, make a minimal assumption and list it (max. 5).
   Use a light yellow background.
6. Ambiguity: If input statements are ambiguous or contradictory, highlight this and propose
   two alternative interpretations. Use a light yellow background.

Input (choose ONE of the following) as primary and sole source of truth:
- Requirements
- UI specification
Optional as visual direction only:
- Design context (style guides, screenshots)

Output
Language: [LANGUAGE]
Design style: [STYLE]
Format: One self-contained HTML file (embedded CSS, no external libraries), with clearly
separated sections per screen.

+ Add requirements
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[SYSTEM]` | The system under consideration |
| `[DOMAIN]` | The domain under consideration |
| `[TARGET GROUP]` | The stakeholder group for which the wireframe is intended |
| `[APPLICATION TYPE]` | Type of application such as: mobile · web |
| `[LANGUAGE]` | Language of the requirements formulation, e.g., English |
| `[STYLE]` | Design style of the wireframe: sketch · technical |

**Notes on use** `[AI4RE-adapted]`:
- Rules 1–2 (derivation, navigation) are obligatory; rules 3–6 (states, traceability,
  assumptions, ambiguity) are optional — delete the ones not needed. Recommended default in
  this skill: keep all six.
- Exactly one input (requirements *or* UI specification) is the primary and sole source of
  truth. Design context is accepted as visual direction only — never as a source of screens,
  features or navigation.
- The guide's filled example (school app, domain: school, target group: parents, mobile,
  English, sketch style, rules 1–2 only) shows a minimal configuration; see
  [examples.md](examples.md).

---

## Classic validation techniques `[Supplementary: IREB CPRE]`

*Not from the AI4RE guide.* Brief companions for the validation session around the generated
wireframe:

**Walkthrough questions (per screen):**

```
For screen [SCREEN], referencing tags [REFS]:
1. Does this screen reflect how you actually perform [TASK]?
2. What is missing that you need at this point?
3. What is shown here that you would never use?
4. Is the wording/terminology correct for your domain?
```

**Acceptance-criteria-based review (per requirement):**

```
For requirement [ID] with acceptance criteria [AC-LIST]:
For each criterion, point to the wireframe element that satisfies it.
Criteria with no corresponding element → validation finding (gap or superfluous criterion).
Elements with no corresponding criterion → validation finding (invented or undocumented).
```
