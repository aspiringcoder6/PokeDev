# Examples — Requirements Traceability

> **Provenance:** Example 1 condenses the worked examples from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. TODO app — tag 40 requirements & trace REQ 4700 `[AI4RE]`

**Tagging input:** requirements R-001…R-040 of a TODO app; taxonomy: *C1 – Work Enablement*
(user-facing business behavior), *C2 – System Trust & Continuity* (quality and reliability),
*C3 – Ecosystem & Governance* (administration, permissions, integrations) — each with
purpose and include criteria. Output format: markdown.

**Output shape (abridged):** legend of the three categories → per requirement `Category`,
`Reasoning`, `Criterion` (quoted), `Secondary match` where applicable. R-002 (login) → C1
via "Supports task execution or work organization", secondary match C2 (security-related)
but primary goal is access enablement; R-027 (audit logging) → C2, secondary match C3.
Pattern: user task features → C1, quality/reliability → C2, admin/roles/integrations → C3.
No requirement had irreducible ambiguity → explicitly stated that no `UNCLEAR`
classifications were necessary.

**Tracing input:** REQ 4700 — "As a user, I want all overview tables across modules to have
a consistent design and behavior…" with three acceptance criteria; artifacts: an interview
transcript, a requirements presentation (PPTX), two design-draft PDFs.

**Output shape (abridged):** summary first → *A) Source Artefacts ("pre")*: interview
transcript (first paragraph, direct quote on consistent tables and justified single/multi
selection) and the presentation "Essential Requirements for Tables in a Software
Application" (slides 3–6, 7–10, 15–18) → *B) Downstream Artefacts ("post")*: "Overview
Table Design Draft", pages 1–2, quotes covering all three acceptance criteria; the menu-bar
draft marked *indirectly related* only → *Not Found*: code modules, test cases, validation
results → *Coverage of Acceptance Criteria* table → *Gaps* → *Recommendation*: record the
pre/post links in the RM tool, keep a per-module variance log, expand the Definition of
Done (UI tests, visual snapshots, accessibility), plan UAT.

**Why it is good:** every tag cites its criterion and discloses secondary matches; every
link has document + location + quote; missing artifact classes are reported, not skipped;
the report ends in actionable next steps.

## 2. Automotive — trace a braking requirement for an ISO 26262 audit `[AI4RE-adapted]`

**Input:** REQ-BRK-112 "When the driver releases the accelerator pedal above 30 km/h, the
regenerative braking system shall decelerate the vehicle at 0.8–1.2 m/s² unless ABS is
active." Artifacts: HARA report, system architecture document, two software unit designs,
HIL test specification.

**Output (abridged):**
- **Pre:** HARA report, §4.2 "Unintended deceleration" (hazard H-07, ASIL B) — direct quote;
  classification "pre".
- **Post:** architecture doc §6.1 (torque blending module, quote), unit design SWU-RegenCtrl
  §3 (deceleration limiter, quote), HIL test spec TC-0455/TC-0456 (deceleration corridor
  verified at 40/80/120 km/h) — all "post".
- **Not found:** the ABS-active exception appears in *no* test case. Reported explicitly as
  a verification gap, not inferred as covered because a test is "about braking".
- **Synonym note:** artifacts use "recuperation" for "regenerative braking" — literal search
  would have missed the unit design; synonym expansion caught it.
- **Recommendation:** add a HIL case for the ABS interlock; record links in the safety case;
  SME review required (functional safety context).

## 3. Banking — tag requirements against a compliance taxonomy `[AI4RE-adapted]`

**Input:** 60 requirements for a payment platform. Taxonomy: *K1 – Customer Transaction*
(include: describes a customer-initiated payment action), *K2 – Regulatory & Audit*
(include: implements a PSD2/AML/KYC obligation, defines retention or reporting), *K3 –
Platform Operations* (include: deployment, monitoring, capacity, internal administration).
Output: CSV for import into the RM tool.

**Output (excerpt):**

| ID | Category | Reasoning | Criterion | Secondary |
|---|---|---|---|---|
| P-014 | K2 | Strong customer authentication implements a PSD2 obligation | "implements a PSD2/AML/KYC obligation" | K1 (login is customer-facing), but primary goal is regulatory compliance |
| P-031 | UNCLEAR | "The system must handle transactions efficiently" — intent ambiguous: throughput target (K3) or customer experience (K1)? Missing: measurable target and beneficiary | — | — |

**Why it is good:** the reproducibility rule matters here — compliance tagging must be
auditable; the FR/NFR trap ("efficiently") is routed to `UNCLEAR` with a concrete question
instead of guessing; secondary matches document the K1/K2 overlap for taxonomy sharpening.

## 4. Cloud/microservices — ownership tagging plus coverage matrix `[AI4RE-adapted]`

**Input:** 25 requirements for an order-management platform; taxonomy = service ownership
(*S1 – Order Service*, *S2 – Inventory Service*, *S3 – API Gateway/Platform*, include
criteria per service boundary). After tagging, trace the eight S1 requirements against
OpenAPI specs, ADRs and the contract-test suite.

**Output (abridged):** tagging table with criterion citations; two requirements spanning
order placement *and* stock reservation get S1 as primary (primary goal: order acceptance)
with S2 disclosed as secondary — exposing a service-boundary ambiguity the team must
resolve. Trace matrix (requirements × {OpenAPI, ADR, contract tests}, cells = "post" +
location): 6/8 requirements covered by contract tests; REQ-ORD-19 (idempotent retries)
appears in ADR-012 but in no test — listed as a gap with the recommendation to add a
contract test before the next release. `Assumption:` the ADR repository is complete —
flagged as possible selection bias since only S1's own repo was provided.

**Why it is good:** single-label rule still applies under shared-ownership pressure;
the matrix makes the "designed but never verified" gap visible; selection bias in the
artifact set is called out instead of silently accepted.
