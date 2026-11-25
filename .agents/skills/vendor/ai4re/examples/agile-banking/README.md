# Scenario: Retail Banking Onboarding — Transcript to Backlog (W2)

**Domain:** banking · **Process:** Scrum (SAFe-compatible) · **Skills:** 5

## The request

> "Here's the recording transcript of our customer-onboarding workshop. Make me a
> sprint-ready backlog, with tests for the KYC part."

## Master classification & plan

**W2** (transcript → backlog) + test derivation. Central clarification round: KYC
jurisdiction (answer: EU/AMLD5, `Assumption:` no US customers — listed), test format
(Gherkin), definition of ready. GDPR reminder: workshop recording contains personal data.

## Walkthrough (abridged artifacts)

**1. Refine transcription — `elicitation-transcription`**
Speaker-labeled, verbatim-faithful transcript; hesitations around the risk-scoring
discussion preserved as `[speaker uncertain]` — that uncertainty is elicitation signal,
not noise. Normalization offered as separate step, declined.

**2. Extraction — `requirements-extraction`**
Candidate table with verbatim quotes: 17 candidates, 3 gaps ("nothing said about
politically exposed persons" → open question), interdependency noted (address
verification precedes account activation).

**3. User stories — `requirements-writing`**
INVEST stories with Given/When/Then; compliance-heavy candidates deliberately *not*
forced into story format — two KYC rules kept as ISO 29148-style system requirements
(the guide's over-reliance-on-template pitfall). Synonym table fixes "client" vs.
"customer" vs. "prospect".

**4. Test cases — `requirements-translation`**
Gherkin-compatible table for the KYC stories: positive (valid ID document), negative
(sanctions-list hit), edge (expired document on submission day). Uncovered test types
named: performance, penetration — routed to specialist teams.

**5. Tagging — `requirements-traceability`**
Tags: component (onboarding, KYC-engine), compliance-relevance (AMLD5, GDPR), MoSCoW,
sprint-candidate. Trace: workshop statement → candidate → story → test case.

## Consolidated deliverable

Sprint-ready backlog (14 stories + 2 system requirements), KYC test table, tag set for
Jira import (CSV offered), consolidated assumptions (2), open questions (5 — PEP handling
escalated to compliance). Draft label: compliance officer sign-off required before
implementation.
