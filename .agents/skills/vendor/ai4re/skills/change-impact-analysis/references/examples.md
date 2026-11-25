# Examples — Change Impact Analysis

> **Provenance:** Example 1 condenses the worked example from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. Insurance — family accident insurance eligibility change `[AI4RE]`

**Change request:** "The Entry Age for the Family accident insurance goes down to minimum
22 years and the family members no longer have to live within the same household but only
dependent children and marital or civil partners are eligible for co-insurance."

**Provided artifacts:** requirements list (.docx), use case descriptions (.docx), UC
diagram (.png), flowchart (.pdf), UML diagram (.pdf), GUI prototype (.docx).

**Output shape (abridged):**
- *CR elements identified:* (1) minimum entry age 25 → 22; (2) same-household rule
  removed; (3) eligibility narrowed to dependent children and marital/civil partners.
- *Impact table* (~20 rows) spanning requirements (REQ-003 age rule, REQ-005 household
  condition, REQ-008 household checkbox, REQ-016 error text, REQ-012 EligibilityCheck,
  REQ-010 PremiumCalculator as *potential side effect*), use cases (UC-03 update, UC-05
  remove/reframe, UC-04 amend), UC diagram nodes, flowchart branches, UML elements
  (ProductRule.minEntryAge, ApplicationValidator.validateHousehold →
  validateCoInsuredEligibility, Person.relationship enum), GUI elements, and interfaces
  (Policy Admin System contract check, Address Verification scope). Every row cites its
  source file and the exact edit location, often with proposed new wording.
- *Edit points by document* · *Suggested responsibilities* (RE/PO, Legal/Compliance,
  Architecture, UX, QA, Integration, Release) · *Risks* (undefined "dependent child",
  downstream Policy Admin rejection, error-catalog drift, rule versioning/effectiveFrom) ·
  *Suggested missing artifacts* (business rule catalog entry, data dictionary update, test
  spec, interface contract note) · *Validation checklist before release*.

**Why it is good:** CR decomposed first; textual, model, UI *and* logic/interface impacts
covered; exact locations and proposed wording per row; side effects marked as "review, may
be no change"; definition gaps routed to Legal instead of guessed.

## 2. Automotive — extend reversing camera activation `[AI4RE-adapted]`

**Change request:** "The rear-view camera shall also activate automatically when the
parking assist function is engaged, not only when reverse gear is selected."

**Provided artifacts:** system requirements spec, camera software requirements, HARA/
safety analysis excerpt, signal catalog (CAN matrix), HMI spec.

**Output (abridged impact table logic):**
- SYS-REQ-114 "Camera activates on reverse gear" → *functional rule change*: add second
  activation trigger; exact location: SYS-REQ-114, proposed wording supplied.
- Signal catalog → *interface change*: new activation source signal `PA_Engaged` must be
  consumed; source: `CAN_matrix_v7.xlsx`, row for camera ECU.
- HARA item H-23 (unintended camera image while driving) → *safety re-assessment needed*:
  new activation path may change exposure; `Assumption:` ASIL rating unchanged — flagged
  for functional safety review, not decided. `[Supplementary: ISO 26262]` referenced as
  validation need only.
- HMI spec → *UI addition*: display priority conflict between parking-assist overlay and
  camera image; owner: HMI team.
- *Missing artifact:* deactivation criteria (speed threshold when PA engaged) undefined —
  definition gap for systems engineering.

**Why it is good:** the safety-critical dimension is flagged as a validation need with an
owner, never resolved by the AI (business-rule pitfall applied to safety rules).

## 3. Medical device — infusion pump alarm threshold change `[AI4RE-adapted]`

**Change request:** "The occlusion alarm shall trigger at 800 mbar instead of 1000 mbar
for the pediatric infusion set."

**Provided artifacts:** SRS, risk management file excerpt (ISO 14971), alarm system spec,
IFU draft, verification test protocol.

**Output (abridged):**
- SRS-ALM-041 threshold value → *parameter change*, exact location and new value.
- Alarm system spec → *classification check*: does the earlier trigger change alarm
  priority per IEC 60601-1-8? Routed to safety engineer — *not* treated as a cosmetic
  number edit (business-rule pitfall: regulatory constraint, not wording).
- Risk management file → *mandatory update*: risk control measure references 1000 mbar;
  residual-risk evaluation must be repeated; owner: Risk Manager.
- IFU section 6.2 and verification protocol TC-ALM-12/13 → *documentation and test
  updates* with exact locations.
- *Dependency:* pediatric set detection — how does the pump know which set is mounted?
  Sensor/data-model impact checked (coverage sweep: data model, service logic); `Open
  question:` set identification mechanism not documented in provided artifacts.
- *Missing artifact:* regulatory change assessment (does this require notification to the
  notified body?). Owner: Regulatory Affairs.

**Why it is good:** coverage sweep finds the data-model dependency behind a "simple"
threshold change; regulatory consequences become owned validation needs.

## 4. Cloud / microservices — e-commerce checkout currency support `[AI4RE-adapted]`

**Change request:** "Checkout must support payments in CHF in addition to EUR."

**Provided artifacts:** user story backlog export, OpenAPI specs for checkout and payment
services, event schema registry excerpt, architecture diagram (C4 level 2).

**Output (abridged):**
- US-231 "pay in EUR" and acceptance criteria → *functional extension*, exact story ID and
  proposed criteria wording.
- `POST /payments` OpenAPI spec → *API contract change*: `currency` enum extended; source:
  `payment-service/openapi.yaml`, schema `PaymentRequest.currency` — consumers listed from
  the architecture diagram (checkout, invoicing, refund service).
- Event `PaymentCaptured` v3 → *schema evolution*: additive change, but refund service
  pins v2 → *dependency/risk* row; owner: platform team.
- Pricing service → *potential side effect*: rounding rules for CHF (0.05 rappen rounding)
  are a business rule — `Assumption:` Swiss rounding applies; flagged for Product/Finance
  confirmation instead of silently encoded.
- Reports/analytics → *coverage sweep hit*: revenue dashboards aggregate in EUR; FX
  conversion source undefined → *missing artifact:* currency conversion policy. Owner:
  Finance + Data team.

**Why it is good:** the category sweep (API, integration, reports) surfaces impacts far
from the checkout UI; consumer fan-out is derived from the architecture diagram rather
than guessed; granularity grouped by service for clear ownership.
