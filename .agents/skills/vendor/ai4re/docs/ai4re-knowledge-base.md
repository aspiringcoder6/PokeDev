# AI4RE Knowledge Base

Structured analysis of the [IREB AI4RE Prompt Guide](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/overview)
that this repository is built on. Source tags per [NOTICE.md](../NOTICE.md).

## 1. Task taxonomy `[AI4RE]`

The guide organizes 23 RE use cases into 9 activity clusters under the 4 IREB core
activities. This repository maps each cluster to one skill:

| IREB activity | Cluster | Use cases | Skill |
|---|---|---|---|
| Elicitation | Explore | Introduce a New Domain · Identify Stakeholders · Prepare Interview · Plan Workshop | `elicitation-preparation` |
| Elicitation | Transcribe | Refine Transcription · Transcribe Whiteboard Images | `elicitation-transcription` |
| Elicitation | Extract | Identify Requirements | `requirements-extraction` |
| Documentation | Formulate | Specify Requirement · Decompose Requirement · Generate Synonym Table | `requirements-writing` |
| Documentation | Translate | Generate Model From Text · Generate Text From Model · Explain Requirements in Simple Language · Generate Persona · Generate Test Cases · Generate Requirements From Source Code | `requirements-translation` |
| Validation | Validate | Generate Wireframe | `requirements-validation` |
| Validation | Verify | Analyze Requirements Consistency · Check Model Consistency · Compare Specification With Source Code | `requirements-verification` |
| Management | Align | Analyze Change Request Impact | `change-impact-analysis` |
| Management | Assign* | Tag Requirements · Trace Requirements | `requirements-traceability` |

\* Guide spelling: "Asign" [sic].

Each guide page follows the same anatomy: **(1) RE task description → (2) AI approach →
(3) Conclusion → Prompt Template (configuration + variables) → Filled example with sample
output → Variable definitions → Pitfalls & Tips (risk/mitigation pairs).**

## 2. Template anatomy `[AI4RE]`

Every AI4RE prompt template uses the same configuration frame:

```
AI's role:  <expert persona, usually domain- or method-specific>
My role:    <requester persona, usually "Requirements engineer of a [SYSTEM]">
My purpose: <quality goal of the output>
Task:       <instruction, often with numbered steps and conditional branches>
Format:     <explicit output format>
Input:      <the artifact, or "+ Add file …">
```

Variables in `[SQUARE_BRACKETS]`; recurring ones: `[DOMAIN]`, `[SYSTEM]`, `[QUALITY]`,
`[FORMULATION]`, `[FORMAT]`, `[LANGUAGE]`, `[STAKEHOLDER_GROUP]`.

## 3. Prompt pattern catalog `[AI4RE-adapted]`

Consolidated from all 23 use cases (pattern names partly `[Supplementary]`):

**Framing patterns** — dual role prompting (AI role + requester role); purpose priming;
context anchoring (`[DOMAIN]`/`[SYSTEM]`/`[SUBJECT]`); language priming; audience
calibration (jargon-free for a named stakeholder group).

**Procedure patterns** — stepwise task decomposition (numbered steps, chain of thought);
conditional branching (if standard found / else); interactive clarification
(ask-before-proceed); plan-confirm-execute; prompt chaining / conversation staging
(multi-prompt sequences like the five domain-briefing artifacts); chunking with
user-selected starting group; two-phase refinement (faithful first, normalize on request);
iterative re-runs until no new findings.

**Grounding patterns** — strict grounding / sole source of truth (term only if in the
document, quote-evidence per candidate, "choose ONE input"); evidence quoting (verbatim
reference column, exact element names, exact file paths); artifact attachment as template
step ("+ Add file with organizational chart"); missing-input guard; negative-space
prompting (report gaps and missing artifacts as findings).

**Quality patterns** — quality-standard anchoring (INVEST, ISO 29148, INCOSE, IREB CPRE,
SMART); self-validation loop (validate → request missing info → regenerate); assumptions
listed separately (bounded budgets, e.g. max 5); uncertainty marking (`[inaudible]`,
hypothesis labels); ambiguity surfacing with alternative interpretations; framework
anchoring (Onion Model, MoSCoW); target-quantity constraints (3–7 goals).

**Delivery patterns** — output format constraint (fixed table schemas, named artifacts,
self-contained HTML); inline traceability marking (IDs, "Ref: US-1" tags); recommendation
closing (next steps, MVP subset); risk callouts; **draft-not-decision** (the guide's
universal rule: AI output is a draft requiring expert validation).

## 4. Roles `[AI4RE]`

AI personas used by the guide: domain expert in `[DOMAIN]` · requirements specification
expert · expert in requirements engineering (and analysis) · stakeholder-analysis /
systems-engineering specialist · interview/elicitation expert · group facilitation expert ·
transcription expert · MBSE/UML modeling expert · business analyst for stakeholder
communication · UX designer · software testing expert · code-analysis specialist · impact
analysis specialist · RE expert with UI/UX expertise.

Requester persona is consistently the **requirements engineer**; audiences include
business analysts, product owners, domain experts, developers, testers, auditors,
executives and end users.

## 5. Quality standards referenced `[AI4RE]`

INVEST · ISO/IEC/IEEE 29148:2018 · INCOSE · IREB CPRE · SMART · formulation standards:
user story incl. acceptance criteria, use case, IEEE, SOPHIST template. Frameworks in
examples: Onion Model (Alexander 2005), MoSCoW, 100-point method, GDPR, ICAO/AIXM (domain
example). This repository additionally operationalizes `[Supplementary]`: EARS, ISO/IEC/
IEEE 29119 (testing), IREB CPRE Glossary definitions.

## 6. Pitfall taxonomy `[AI4RE]`

Recurring risk themes across all Pitfalls & Tips sections, each countered in the skills'
checklists and self-review protocols:

1. **Plausible but wrong** — hallucinated domain facts, invented benchmarks, fabricated
   requirements. → strict grounding, evidence quotes, SME review.
2. **Ambiguity absorption** — AI silently resolves vague input instead of asking. →
   ask-before-assume, assumption marking, alternative interpretations.
3. **Domain/regulatory blindness** — nuances (safety, compliance, terminology) missed. →
   domain context in prompt, expert validation gates.
4. **Overfitting to common patterns** — generic templates where the domain needs tailored
   forms. → domain examples and constraints in the prompt.
5. **Over/under-specification** — invented precision ("99.999%") or silent gaps. → review
   against business goals; NFR sweep; no unsanctioned numbers.
6. **Loss of intent / semantic drift** — syntax preserved, strategic intent or obligation
   level lost (must → should); smoothing transcripts into false clarity. → fidelity scans,
   modal-verb preservation, verbatim-first transcription.
7. **Context ignorance** — architecture, org constraints, interdependencies unknown. →
   attach artifacts (trace matrix, org chart, architecture), category sweeps.
8. **Inconsistent granularity** — abstraction levels mixed. → one level per artifact,
   granularity normalization.
9. **Scale limits** — "lost in the middle" on large inputs, truncated output. → chunking,
   iterative runs, fresh session per comparison.
10. **False confidence / overreliance** — polished output treated as decided. →
    draft-not-decision, mandatory human review points.
11. **Privacy & confidentiality** — transcripts, org charts, production code in external
    AI services (GDPR). → sensitive-data reminders as workflow steps.

## 7. General cautions `[AI4RE]`

From the guide's overview page, encoded as behavioral rules in every skill:
**avoid sharing sensitive data in prompts** · **always validate AI outputs before use** ·
the guide "reflects the current state of a rapidly evolving field … intended for personal
use, inspiration, and discussion, not as a definitive standard."

## 8. Gaps — RE tasks the guide does not (yet) cover

Not covered by any AI4RE use case as of this analysis: prioritization, effort estimation,
requirements negotiation/conflict resolution between stakeholders, review moderation,
baseline/release management. The master skill names these honestly and handles them with
general RE expertise under the same behavioral rules (see
`skills/ai4re-master/references/routing.md`, disambiguation rules). They are natural
extension points for new skills.
