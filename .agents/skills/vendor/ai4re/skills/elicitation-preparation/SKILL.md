---
name: elicitation-preparation
description: >
  Prepares effective requirements elicitation according to the IREB AI4RE Prompt Guide
  (cluster "Explore"). Use when the user wants to build understanding of a new domain
  (introduction, system context, regulations, actors, glossary), identify and classify
  stakeholders (Onion Model, mapping to individuals/roles), prepare a stakeholder interview
  (exploratory or goal-confirmation guide), or plan a requirements workshop (agenda,
  facilitation techniques, follow-up). Triggers include: "introduce me to this domain",
  "domain overview/briefing", "who are the stakeholders", "stakeholder analysis/onion
  model", "interview guide/questions/script", "prepare an interview", "plan/facilitate a
  workshop", "workshop agenda".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Elicitation
  ai4re-cluster: Explore
  ai4re-use-cases: [Introduce a New Domain, Identify Stakeholders, Prepare Interview, Plan Workshop]
---

# Elicitation Preparation

Turns a blank page at project start into elicitation-ready groundwork: a structured domain
briefing, a classified stakeholder landscape, tailored interview guides and a facilitatable
workshop plan — everything that must exist *before* the first stakeholder conversation.

## Provenance

`[AI4RE]` This skill implements the four use cases of the AI4RE Prompt Guide cluster
**Explore** (IREB core activity: *Elicitation*): *Introduce a New Domain*, *Identify
Stakeholders*, *Prepare Interview*, *Plan Workshop*. Workflows, templates, the Onion Model
classification and the pitfalls originate from the guide. `[Supplementary: IREB CPRE,
interviewing/facilitation practice]` Operationalized quality criteria for questions,
stakeholder coverage heuristics and facilitation-technique references beyond the guide are
supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Get familiar with an unfamiliar domain at project start: introduction text, system
  context, regulations and standards, actors/user groups, domain glossary.
- Identify relevant stakeholder groups, prioritize them and classify them with the Onion
  Model (Alexander, 2005); map groups to concrete individuals or roles (e.g. from an
  org chart).
- Prepare a stakeholder interview: a general exploratory guide or a goal-confirmation
  script for a named expert.
- Plan a requirements workshop: agenda, materials, invitations, facilitation techniques,
  conflict handling, documentation and follow-up.

**Do not use when:**
- Elicitation has already happened and transcripts, notes or whiteboard photos must be
  cleaned up or refined → `elicitation-transcription`.
- Requirements must be *identified* in existing material (documents, transcripts) →
  `requirements-extraction`.
- A requirement must be formulated, decomposed or terminology aligned via synonym table →
  `requirements-writing`.
- Content should become a model, test cases, personas or a plain-language explanation →
  `requirements-translation`.
- Requirements should be validated with stakeholders via wireframes →
  `requirements-validation`; checked for internal consistency/contradictions →
  `requirements-verification`.
- The task is assessing the impact of a change → `change-impact-analysis`; or tagging and
  tracing requirements → `requirements-traceability`.

## Roles

- **Claude acts as:** domain expert in the user's domain (ask for the domain if unknown),
  specialized per use case in stakeholder analysis and systems engineering, in conducting
  stakeholder interviews, or in requirements engineering and group facilitation — dual-role
  prompting per AI4RE.
- **Typical users:** requirements engineers and business analysts at the *initial stage of
  a project*; output must be readable for stakeholders and project collaborators who may be
  unfamiliar with the domain.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which use case applies (domain intro / stakeholders / interview /
   workshop). If several apply, sequence them the way the guide does: domain understanding
   → stakeholder identification → interview or workshop preparation.
2. **Establish context.** Determine `[DOMAIN]`, `[SYSTEM]` and the target output format
   (workspace page, Word, plain text). For interviews additionally the interview type
   (exploratory vs. goal confirmation) and interviewee; for workshops the participants and
   workshop goals. Ask for whatever is missing and materially shapes the output.
3. **Clarify or assume.** Ask targeted questions when input is ambiguous (e.g. system
   boundary, regulatory region, participant mix). If the user is unavailable or the gap is
   minor, proceed and prefix every guess with `Assumption:` — the guide's stakeholder
   template makes "make assumptions and list them separately" an explicit instruction;
   apply it in all four use cases.
4. **Check data sensitivity.** These use cases invite uploads of org charts, goal documents
   and recordings. Before processing such artifacts — and whenever the user is about to
   paste one into an *external* AI service — remind them of the guide's caution: personal
   data and confidential structures need approval or anonymization (role IDs instead of
   names). `[AI4RE]` (Identify Stakeholders pitfalls).
5. **Execute** the use-case-specific procedure (below), applying the matching template from
   [references/templates.md](references/templates.md). Ground on artifacts the user
   provided; separate *extracted from input* from *suggested from domain knowledge* —
   domain briefings in particular mix both.
6. **Self-review.** Run the quality gates and the checklist from
   [references/checklists.md](references/checklists.md) against your own output. Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
7. **Deliver.** Output in the requested format, followed by: assumptions, open questions,
   detected risks, and a one-line reminder that the result is a draft requiring expert
   validation — for domain briefings explicitly note that regulations/standards lists need
   sign-off by a qualified professional. `[AI4RE]` (general caution + Introduce a New
   Domain pitfalls).

## Use cases

### 1. Introduce a New Domain `[AI4RE]`

Build foundational domain understanding via a chain of five prompts producing five named
artifacts: **Introduction → System Context → Regulations and Standards → Actors →
Glossary**.

1. Confirm `[DOMAIN]`, `[SYSTEM]`, desired length and format. Ask which of the five
   artifacts the user needs; default to the full chain in the guide's order.
2. **Introduction:** brief, well-structured overview — core purpose, key benefits, common
   use cases — accessible tone for readers unfamiliar with the domain.
3. **System Context:** neighboring systems, their purpose and how they interact with the
   system under consideration.
4. **Regulations and Standards:** list of the most important regulatory frameworks and
   standards; always add the caution that a qualified professional must ensure complete
   technical compliance.
5. **Actors:** user groups with individual goals, tasks and required data flows.
6. **Glossary:** key domain-specific terms with concise definitions.
7. Everything not grounded in user-provided artifacts is domain knowledge: mark uncertain
   or fast-moving items (recent regulations, regional specifics) for expert verification.

Templates: *Introduce a New Domain* (five prompts) in
[references/templates.md](references/templates.md).

### 2. Identify Stakeholders `[AI4RE]`

Produce a prioritized, classified stakeholder landscape as preparation for interviews and
workshops.

1. **Stakeholder groups:** identify all relevant groups for the system, sort by influence
   or importance, classify each with the Onion Model (Alexander, 2005): *System* (core
   layer), *Immediate* (second layer), *Wider* (outer layer). List assumptions separately.
2. Output as a table: `Stakeholder Group | Short Description (max 2 lines) | Priority
   (High/Medium/Low) | Onion Layer`.
3. **Individual mapping (optional second step):** map each group to specific individuals or
   roles from a provided org chart. Group names must match the stakeholder list exactly;
   ambiguous or missing mappings get explicit `Assumption:` notes. Never invent people —
   only use roles/persons present in the provided chart.
4. Close with a recommendation: which high-priority groups to engage first, and that the
   Onion classification be validated in a workshop (practice from the guide's worked
   example).
5. Sensitive-data step 4 of the core workflow applies with full force here (org charts
   contain personal data).

Templates: *Stakeholder Groups* and *Individual Stakeholders* in
[references/templates.md](references/templates.md).

### 3. Prepare Interview `[AI4RE]`

Create an interview guide — the two interview types require different emphases:

- **General exploratory interview:** understand which user roles exist, their tasks, goals,
  problems, work environment and needed resources. Structure the guide in timed sections:
  introduction/logistics → role & responsibilities → current process & information use →
  challenges & pain points → work environment & future vision → conclusion (practice from
  the guide's worked example).
- **Goal confirmation interview:** for a named expert (`[NAME]`, `[DOMAIN]`,
  `[ORGANIZATION]`), verify, update or dismiss already collected main goals from a provided
  document; check for missing goals; converge on 3–7 agreed main goals. Structure: present
  existing goals → verify each (valid? complete? unambiguous?) → identify missing/redundant
  → prioritize → confirm agreement and next steps.

Quality rules for the questions themselves (from the guide's pitfalls): open-ended and
non-leading, no redundant near-duplicates, no overloaded sections, vocabulary matched to
the stakeholder (not generic AI-textbook phrasing), topics prioritized by the stakeholder's
role and project phase. Tailor the guide to the specific stakeholder group — flag that it
is a starting point the requirements engineer must refine.

Templates: *General Exploratory Interview* and *Goal Confirmation Interview* in
[references/templates.md](references/templates.md).

### 4. Plan Workshop `[AI4RE]`

Create a flexible workshop guide for given `[STAKEHOLDERS]` and `[GOALS]`.

1. Confirm participants, goals (eliciting / validating / prioritizing requirements,
   exploring pain points, defining roles-tasks-processes) and constraints (duration,
   on-site/hybrid, facilitation experience of the user).
2. The guide must cover all five parts named in the template: planning (agenda, materials,
   invitations), adapting facilitation techniques to the chosen focus, step-by-step conduct
   with time allocations and example activities, facilitation tips (discussions, conflicts,
   ensuring all voices are heard), and post-workshop documentation and validation.
3. Match techniques to focus (elicitation → brainwriting/story mapping; validation →
   walkthroughs; prioritization → MoSCoW/dot voting; user understanding → journey mapping)
   — but check technique fit to the domain (e.g. regulatory-driven contexts) and to the
   facilitator's skill level; offer simpler alternatives when in doubt. `[AI4RE]`
   (Plan Workshop pitfalls).
4. Do not assume ideal conditions: address limited availability, power imbalances and
   technical constraints the user mentioned — and ask about them if unmentioned.
5. Emphasize follow-up: turning workshop output into traceable requirements is significant
   effort; include a concrete post-workshop validation plan.

Template: *Plan Workshop* in [references/templates.md](references/templates.md).

## Output formats

- **Domain briefing:** five named artifacts — *Introduction* (prose with headings),
  *System Context* (table: System Name | Purpose | Interaction), *Regulations and
  Standards* (table/list with relevance per entry), *Actors* (table: User Group | Goals |
  Typical Tasks | Required Data Flows), *Glossary* (Term | Definition, alphabetical).
- **Stakeholder landscape:** markdown table `Stakeholder Group | Short Description |
  Priority | Onion Layer`, plus separate *Assumptions* block and *Recommendation*; mapping
  matrix `Stakeholder Group | Mapped Person(s)/Role(s) | Notes/Assumptions | Priority |
  Onion Layer`.
- **Interview guide:** timed sections with scripted openings and open questions; goal
  confirmation additionally the goal list under review and per-goal check questions.
- **Workshop guide:** overview table, preparation steps, timed agenda table, techniques per
  focus, facilitation tips, documentation artifacts, follow-up steps.
- Plain markdown unless the user requests another format (`[FORMAT]`: workspace page such
  as Confluence, Word, plain text).

## Quality gates

- **Coverage:** stakeholder lists span all Onion layers including *Wider* (regulators,
  vendors, indirect users); domain briefings cover purpose, context, regulation, actors and
  terminology; interview guides cover roles, tasks, goals, problems, environment and
  resources. `[AI4RE]`
- **Specificity:** no generic textbook output — every question, agenda item and stakeholder
  entry is tailored to `[SYSTEM]` and `[DOMAIN]`. `[AI4RE]` (recurring pitfall across all
  four pages).
- **Groundedness:** individual mappings only from provided artifacts; assumptions listed
  separately; regulations flagged for professional verification. `[AI4RE]`
- **Question quality:** open, neutral, single-topic, stakeholder-appropriate vocabulary.
  `[Supplementary: interviewing practice, operationalizing the guide's pitfalls]`
  Full operationalized checklists in [references/checklists.md](references/checklists.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- Generic-output scan: would this text fit any system in any domain? If yes, re-tailor with
  domain terminology, actual regulations and the named stakeholder groups.
- Leading/redundant-question scan (interviews): no question suggests a preferred answer; no
  two questions ask the same thing; no section is overloaded.
- Coverage scan: Onion *Wider* layer populated; non-obvious stakeholders (compliance,
  operations, data protection, vendors) considered; interview covers all six aim areas;
  workshop guide contains all five required parts including follow-up.
- Grounding scan: no invented individuals, org units or sanctioned facts; every
  non-input-derived statement is marked `Assumption:` or presented as a suggestion.
- Sensitivity scan: did the input contain personal or confidential data — and did I remind
  the user about approval/anonymization before it goes to an external service?
- Realism scan (workshops): plan works under the stated constraints, not just ideal
  conditions; facilitation techniques match the user's stated skill level.

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing any of the four use cases |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
