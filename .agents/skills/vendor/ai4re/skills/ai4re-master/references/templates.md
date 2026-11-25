# Templates — AI4RE Master Consultant

> **Provenance:** `[Supplementary: this repository]` — orchestration templates; the AI4RE
> Prompt Guide defines templates per use case (see the specialized skills), not for
> supervision.

## 1. Intake briefing

Fill this from the user's request and one central round of clarifying questions:

```
Project / system: [SYSTEM]
Domain: [DOMAIN]
RE task(s) detected: [USE_CASES from routing table]
Input artifacts available: [transcripts | spec | models | code | none]
Target artifacts: [stories | spec | trace matrix | report | …]
Formulation standard: [user story | use case | IEEE/ISO 29148 | SOPHIST | EARS | to negotiate]
Quality standard: [IREB CPRE | ISO/IEC/IEEE 29148 | INVEST | INCOSE]
Audience: [technical | mixed | non-technical]
Constraints: [regulatory, organizational, technical]
```

## 2. Workflow plan (present before executing)

```
Plan (n steps):
1. [Step] — skill: [skill-name] → artifact: [artifact]
2. …
Open questions before start: [collected questions from all steps]
```

## 3. Step handoff (between steps)

```
Step [k] complete: [artifact] ([count] items).
Carried forward: glossary [n terms] · assumptions [n] · open questions [n].
Next: step [k+1] — [skill-name].
```

## 4. Final status report

```
# RE Status Report — [SYSTEM]
## Artifacts produced
| Step | Skill | Artifact | Items |
## Quality findings (cross-skill review)
## Consolidated assumptions
## Open questions (need stakeholder input)
## Risks
## Recommended next RE activities
> Draft — requires validation by domain experts and stakeholders.
```
