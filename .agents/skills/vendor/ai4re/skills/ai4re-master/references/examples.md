# Examples — AI4RE Master Consultant

> **Provenance:** `[Supplementary: this repository]` — orchestration examples; each step
> executes `[AI4RE]` procedures from the specialized skills.

## 1. Fuzzy greenfield request (software project)

**User:** "We're building a fleet management platform for e-scooters. Help me with the
requirements."

**Master behavior:** Classification: broad greenfield → workflow W1. No input artifacts
exist yet, so plan steps 1–3 only (domain briefing, stakeholder table, interview guide) and
say that extraction/specification follow once elicitation material exists. Central
questions: target market/regulation (EU city licenses?), B2B or B2C, formulation standard
preference. Deliverable: domain introduction + stakeholder table + interview guides, one
consolidated open-questions list.

## 2. Mixed multi-task request (agile/banking)

**User:** "Here's the transcript of our onboarding workshop. Make me a backlog and tests
for the KYC part."

**Master behavior:** Classification: W2 (transcript → backlog) + test derivation.
Plan: refine transcript → extract candidates → user stories (INVEST) → test cases for
KYC stories → tag by component/compliance-relevance. One central question round: KYC
regulation scope (which jurisdiction?), definition of done for "tests" (Gherkin?).
Handoffs announced between steps; final report consolidates 3 assumptions and 5 open
questions, flags AML/KYC items for compliance review.

## 3. Single-task request — no orchestration

**User:** "Rewrite this requirement as a user story with acceptance criteria."

**Master behavior:** Exactly one use case (Specify Requirement) → route directly to
`requirements-writing`, no plan presentation, no orchestration overhead. The master skill
notes internally that it stepped aside.

## 4. Out-of-AI4RE-scope request (prioritization)

**User:** "Prioritize these 40 requirements."

**Master behavior:** No AI4RE use case covers prioritization. Say so explicitly, offer
general RE support (e.g. preparing a MoSCoW/WSJF assessment as a *draft* with assumptions
marked), and apply the behavioral rules regardless. Suggest `requirements-traceability`
tagging as a supporting step (tags: business value, risk, dependency) — a documented
extension point for a future skill.
