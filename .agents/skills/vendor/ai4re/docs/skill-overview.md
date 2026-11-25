# Skill Overview

10 skills: 9 specialized (one per AI4RE cluster) + 1 supervisor. Full routing details:
[skills/ai4re-master/references/routing.md](../skills/ai4re-master/references/routing.md).

| Skill | IREB activity / cluster | AI4RE use cases | Typical triggers | Key outputs |
|---|---|---|---|---|
| [ai4re-master](../skills/ai4re-master/SKILL.md) | all (supervisor) | routes all 23 | broad/fuzzy/multi-task RE requests | workflow plan, consolidated deliverables, status report |
| [elicitation-preparation](../skills/elicitation-preparation/SKILL.md) | Elicitation / Explore | Introduce a New Domain · Identify Stakeholders · Prepare Interview · Plan Workshop | "new domain", "who are the stakeholders", "interview questions", "workshop agenda" | domain briefing artifacts, stakeholder table (Onion Model), interview guides, workshop guide |
| [elicitation-transcription](../skills/elicitation-transcription/SKILL.md) | Elicitation / Transcribe | Refine Transcription · Transcribe Whiteboard Images | raw transcript, whiteboard photo | speaker-labeled transcript, structured whiteboard text |
| [requirements-extraction](../skills/requirements-extraction/SKILL.md) | Elicitation / Extract | Identify Requirements | "find the requirements in …" | candidate table with verbatim source quotes, gaps & open questions |
| [requirements-writing](../skills/requirements-writing/SKILL.md) | Documentation / Formulate | Specify Requirement · Decompose Requirement · Generate Synonym Table | "rewrite as user story", "break down", "synonym table" | standard-conformant requirements, decompositions, synonym table |
| [requirements-translation](../skills/requirements-translation/SKILL.md) | Documentation / Translate | Generate Model From Text · Generate Text From Model · Explain in Simple Language · Generate Persona · Generate Test Cases · Generate Requirements From Source Code | "model this", "explain for execs", "persona", "test cases", "requirements from code" | PlantUML/Mermaid/BPMN models, plain-language summaries, personas, test case tables, reverse-engineered specs |
| [requirements-validation](../skills/requirements-validation/SKILL.md) | Validation / Validate | Generate Wireframe | "wireframe/mockup for review" | annotated HTML/ASCII wireframes with traceability tags |
| [requirements-verification](../skills/requirements-verification/SKILL.md) | Validation / Verify | Analyze Requirements Consistency · Check Model Consistency · Compare Specification With Source Code | "contradictions?", "compare diagrams", "code vs spec" | categorized findings reports, discrepancy tables (Match/Partial/Missing/Extra) |
| [change-impact-analysis](../skills/change-impact-analysis/SKILL.md) | Management / Align | Analyze Change Request Impact | "what does this CR affect" | six-column impact table, edit points, owners, risks |
| [requirements-traceability](../skills/requirements-traceability/SKILL.md) | Management / Assign | Tag Requirements · Trace Requirements | "classify/tag", "trace matrix" | tagged requirement sets, trace matrices |

## Shared behavior (all skills)

Every skill: asks clarifying questions on ambiguous input · marks guesses with
`Assumption:` · grounds output strictly on provided artifacts · self-reviews against its
checklists before delivering · ends with assumptions, open questions and risks · labels
results drafts requiring expert validation · reminds about sensitive data when relevant.

## File anatomy per skill

`SKILL.md` (workflow, quality gates, self-review) + `references/`: `templates.md` (AI4RE
templates, verbatim-preserved), `checklists.md`, `prompt-patterns.md`, `examples.md`,
`system-prompt.md` (standalone prompt for non-Claude tools).
