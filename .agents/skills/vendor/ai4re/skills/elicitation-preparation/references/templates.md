# Templates — Elicitation Preparation

> **Provenance:** `[AI4RE]` All templates below originate from the IREB AI4RE Prompt Guide,
> cluster *Explore* — pages [Introduce a New Domain](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2315780185),
> [Identify Stakeholders](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2315780224),
> [Prepare Interview](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2315780252),
> [Plan Workshop](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2315780280).
> Wording is preserved; formatting is adapted for skill use and obvious transcription
> artifacts are fixed. Sections marked `[AI4RE-adapted]` or `[Supplementary: …]` are noted
> as such.

All templates follow the AI4RE configuration anatomy: **AI's role · My role · My purpose ·
Task · Format · Input/attachments**. Resolve every `[VARIABLE]` before use — either from
the user's request or by asking. The guide's examples target Confluence; adapt the "optimize
for Confluence" instructions and fixed titles to the user's actual workspace
`[AI4RE-adapted]`.

---

## 1. Introduce a New Domain `[AI4RE]`

**Purpose:** Build foundational domain understanding via a chain of five prompts. Run the
configuration prompt first; the follow-up prompts continue in the same conversation.

### 1.1 Prompt: Overview

```
AI's role: Domain expert in [DOMAIN] with extensive experience in both of its technical
foundations and practical applications.
My role: Requirements engineer, responsible for defining system requirements for [SYSTEM]
at the initial stage of a project.
My purpose: To proceed effectively, I need a foundational understanding of the domain.

Task: Create a brief, well-structured overview titled "Introduction". The overview should:
- Target an audience of stakeholders and project collaborators, some of whom may be
  unfamiliar with the domain.
- Explain the system's core purpose, key benefits, and common use cases.
- Provide a clear and informative introduction that supports the early requirements
  engineering process.
- Clearly formatted and professionally written for ease of reading in a collaborative
  workspace.
- Maintaining an accessible tone, avoiding unnecessary technical jargon while preserving
  essential accuracy.

Format:
Length: [LENGTH]
Format: [FORMAT]
```

### 1.2 Prompt: System Context

```
I want to understand the context of the system.
Are there any other systems with which it interacts? List these systems and describe their
purpose and how they interact.
The title should be "System Context".
Format: [FORMAT]
```

### 1.3 Prompt: Regulations and Standards

```
What regulatory requirements need to be considered when specifying a [SYSTEM]?
What are the relevant regulations and standards?
Create a list of the most important ones optimized for Confluence. The title is
"Regulations and Standards."
```

### 1.4 Prompt: Actors

```
What are the system's user groups? Describe their individual goals and tasks, as well as
the required data flows.
Create a list of user groups and their respective goals and tasks. Optimize for Confluence
and use the title "Actors."
```

### 1.5 Prompt: Glossary

```
I want to become familiar with the terms used in this domain.
Create a glossary of domain-specific terms. Provide a list of key terms.
The title is "Glossary."
Format: [FORMAT]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[DOMAIN]` | The domain under consideration |
| `[SYSTEM]` | The system under consideration |
| `[LENGTH]` | The length of the output text (e.g. the number of words) |
| `[FORMAT]` | e.g. word · confluence · plain text |

**Practice from the guide's worked example** `[AI4RE-adapted]`: the Introduction covers
purpose, benefits, use cases, high-level components, stakeholder landscape, relevance to RE
and a closing *Recommendation* (engage domain experts early, review key regulations, define
stakeholder roles and data flows). Always append the caution that regulations/standards
lists require verification by a qualified professional.

---

## 2. Identify Stakeholders `[AI4RE]`

**Purpose:** Identify, prioritize and classify stakeholder groups as preparation for
interviews and workshops; optionally map groups to concrete individuals or roles.

### 2.1 Prompt: Stakeholder Groups

```
AI's role: domain expert in [DOMAIN], specialized in stakeholder analysis and systems
engineering.
My role: Requirements engineer defining a [SYSTEM].
My purpose: Identify relevant stakeholder groups as preparation for stakeholder interviews
and workshops.

Task:
- Identify all relevant stakeholder groups for the system.
- Sort by influence or importance.
- Classify each group using the Onion Model (Alexander, 2005):
  - System (core layer)
  - Immediate (second layer)
  - Wider (outer layer)
- If necessary, make assumptions and list them separately.

Format: [FORMAT]
```

### 2.2 Prompt: Individual Stakeholders

```
Map each stakeholder group to specific individuals or roles. Where mapping is ambiguous or
missing, state assumptions explicitly. Ensure that group names match those in the
Stakeholder List.

+ Add file with organizational chart
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[DOMAIN]` | The domain under consideration |
| `[SYSTEM]` | The system under consideration |
| `[FORMAT]` | e.g. Confluence-ready markdown table using pipe separators |

**Practice from the guide's worked example** `[AI4RE-adapted]`: format the result as
`Stakeholder Group | Short Description (max 2 lines) | Priority (High/Medium/Low) | Onion
Layer (System/Immediate/Wider)`; close with an *Assumptions* block (scope, regulatory
context, architecture) and a *Recommendation* (start with high-priority groups, validate
the Onion classification in a workshop, create RACI/interface maps). For the mapping
matrix, external stakeholders not in the org chart are mapped to their internal owners.

**Sensitive data** `[AI4RE]`: uploading an org chart to a public AI service is usually not
permitted without prior approval (personal data, confidential structures). Check IT
security / GDPR policies, involve the Data Protection Officer if in doubt, or anonymize the
chart (role IDs or generic role names) before uploading.

---

## 3. Prepare Interview `[AI4RE]`

**Purpose:** Create an interview guide — exploratory (broad understanding) or goal
confirmation (converge on agreed main goals).

### 3.1 Prompt: General Exploratory Interview

```
AI's role: Expert in conducting stakeholder interviews to gather requirements
My role: Requirements engineer working on specifying the requirements for a [SYSTEM].
My purpose: Conducting general exploratory stakeholder interviews. My aim is to understand
which user roles exist, their tasks, their goals, the problems they face while performing
their work, the environment in which they work, and the resources they need to complete
their tasks.

Task: Create an interview guide for a general exploratory interview focused on the
[SYSTEM].

Format of script: [FORMAT]
```

### 3.2 Prompt: Goal Confirmation Interview

```
AI's role: Expert in requirements elicitation
My role: Requirements engineer
My purpose: Conducting an interview with [NAME], who is an expert in [DOMAIN]. The person
is an employee of [ORGANIZATION]. My goal is to verify, update, or dismiss already
collected system's main goals provided in the Word file. I also want to check for any
missing main goals. At the end I would like to have 3-7 main goals collected and agreed.

Task: Create an interview script as a guideline.

Format of script: [FORMAT]

+ Add word file with goals
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[SYSTEM]` | The system under consideration |
| `[FORMAT]` | e.g. word · confluence · plain text |
| `[NAME]` | Name of the interview partner |
| `[DOMAIN]` | The domain under consideration |
| `[ORGANIZATION]` | Organization or company the interview partner is working for |

**Practice from the guide's worked examples** `[AI4RE-adapted]`: structure the exploratory
guide in timed sections — Introduction & Context · Role & Responsibilities · Current
Process & Information Use · Challenges & Pain Points · Work Environment & Future Vision ·
Conclusion. Structure the goal-confirmation script as — Introduction · Context Setting ·
Presentation of Existing Goals · Verification of Each Goal ("still valid?", "anything
missing?", "wording unambiguous?") · Missing/Redundant Goals · Prioritization & Agreement ·
Final Review & Next Steps. Close with the recommendation to use the script as a flexible
guideline, document feedback precisely and share consolidated results for confirmation.

---

## 4. Plan Workshop `[AI4RE]`

**Purpose:** Create a flexible, facilitatable guide for a requirements workshop.

```
AI's role: expert in requirements engineering and group facilitation.
My role: requirements engineer
Purpose: conducting a requirements workshop to gather stakeholder input for a [SYSTEM].
Workshop's stakeholders (participants): [STAKEHOLDERS]
Workshop's goals: [GOALS]

Task: Create a flexible workshop guide that includes:
- How to plan the workshop (agenda, materials, stakeholder invitations)
- How to adapt the facilitation techniques to the chosen focus
- How to conduct the workshop step by step, with time allocations and example activities
- Tips for facilitating discussions, handling conflicts, and ensuring all voices are heard
- Advice on documenting and validating the results afterward

Format: [FORMAT]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[SYSTEM]` | The system under consideration |
| `[STAKEHOLDERS]` | Participants, such as: end users · business owners · IT staff · domain experts · decision-makers · system developers · regulatory representatives |
| `[GOALS]` | Workshop goals, such as: eliciting new requirements · validating existing requirements · prioritizing requirements · exploring pain points or challenges · defining user roles, tasks, and processes |
| `[FORMAT]` | e.g. plain text · word |

**Practice from the guide's worked example** `[AI4RE-adapted]`: deliver an overview table
(objective, duration, participants, format, deliverables), preparation steps, a timed
agenda, a techniques-per-focus table (elicitation → brainwriting/"How might we…"/user story
mapping; validation → walkthroughs/3-point check; prioritization → MoSCoW/100-point/dot
voting; user understanding → role/journey mapping), facilitation tips per situation
(dominant/quiet participants, conflict, drift, energy loss), documentation artifacts with
responsibilities, post-workshop validation steps (summary to participants within 3–5 days,
repository update, lessons learned) and adaptations for half-day/hybrid/multi-group setups.
