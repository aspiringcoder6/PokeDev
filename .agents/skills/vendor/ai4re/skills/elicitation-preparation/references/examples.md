# Examples — Elicitation Preparation

> **Provenance:** Example 1 condenses the worked examples from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. Aviation — introduce the AIS domain via prompt chain `[AI4RE]`

**Input:** Requirements engineer at the initial stage of a project for an Aeronautical
Information Service (AIS) system; needs foundational domain understanding.

**Configuration:** AI's role: domain expert in AIS · My role: requirements engineer
defining system requirements for an AIS system · Length: 1000 words · Format: Confluence.

**Output shape (abridged), one artifact per prompt in the chain:**
- *Introduction* — what AIS is (ICAO-governed collection/management/dissemination of
  aeronautical data), core purpose, key benefits (safety, efficiency, compliance,
  interoperability), common use cases (flight planning, NOTAM management, charting, data
  exchange), high-level components, stakeholder landscape, relevance to RE, closing
  *Recommendation* (engage domain experts early, review ICAO Annex 15/AIXM, define
  stakeholder roles and data flows).
- *System Context* — table of interacting systems (ATM, flight planning, NOTAM, charting,
  AIXM database, SWIM, MET, airport operations, regulatory oversight, military
  coordination) with purpose and interaction.
- *Regulations and Standards* — ICAO Annex 15, PANS-AIM, EU 2017/373 and 2020/469,
  EUROCONTROL guides, AIXM, SWIM, ISO 19100, each with type and relevance.
- *Actors* — user groups (ATCOs, pilots/flight planners, ANSPs, airport operators,
  military, regulators, admins, data originators, international consumers) with goals,
  tasks and required data flows.
- *Glossary* — ~20 key terms (AIP, NOTAM, AIXM, SWIM, AIM, ENR, AD, Digital NOTAM, …).

**Why it is good:** one configuration, five reusable named artifacts; consistent
terminology across all five; each artifact ends collaboration-ready; the regulations list
is exactly where the guide's pitfall demands professional verification — flag it.

## 2. Medical — identify stakeholders for a remote patient monitoring platform `[AI4RE-adapted]`

**Input:** "We're building a remote patient monitoring platform (wearable sensors + clinic
dashboard) for a hospital group. Who do we need to talk to?"

**Configuration:** AI's role: domain expert in digital health / telemonitoring,
specialized in stakeholder analysis · System: remote patient monitoring (RPM) platform ·
Format: markdown table.

**Output (excerpt):**

| Stakeholder Group | Short Description | Priority | Onion Layer |
|---|---|---|---|
| Monitoring nurses / triage staff | Watch dashboards, respond to alerts daily | High | System |
| Treating physicians | Review trends, adjust therapy | High | System |
| Patients & informal caregivers | Wear sensors, need comprehensible feedback | High | Immediate |
| Clinical IT / EHR integration team | HL7 FHIR interfaces to the hospital EHR | High | Immediate |
| Data protection officer (GDPR/health data) | Approves processing of special-category data | High | Immediate |
| Notified body / regulator (MDR) | Platform likely a medical device — conformity assessment | High | Wider |
| Health insurers / payers | Reimbursement rules shape usage scenarios | Medium | Wider |
| Device vendors | Sensor firmware, connectivity SLAs | Medium | Wider |

`Assumption:` platform classified as a medical device under EU MDR (to be confirmed with
regulatory affairs). *Recommendation:* interview monitoring nurses and the DPO first;
validate the Onion classification in a joint clinical/IT workshop.

**Why it is good:** the Wider layer is populated (regulator, payers, vendors) — the layer
generic lists miss; safety- and privacy-critical stakeholders rank high; the classification
assumption is separate and flagged for confirmation, not silently baked in.

## 3. Automotive — goal confirmation interview for an OTA update system `[AI4RE-adapted]`

**Input:** "I have a draft list of five main goals for our vehicle over-the-air (OTA)
software update system. Prepare an interview with Dr. Weber, our E/E architecture lead, to
confirm them."

**Configuration:** AI's role: expert in requirements elicitation · Interviewee: Dr. Weber,
expert in automotive E/E architecture, employee of the OEM · Goal: verify/update/dismiss
the five draft goals, check for missing ones, end with 3–7 agreed main goals · Provided
artifact: the draft goal list.

**Output (abridged script):** Introduction (2 min) → context setting: OTA scope = ECU
software, not map data (`Assumption:` — confirm in the interview) → present the five draft
goals verbatim from the provided list → per goal: "Still valid given the move to a central
vehicle computer?", "Is 'fast rollout' unambiguous — hours, days?", "Anything missing in
this goal's scope?" → probe for missing goals with domain-specific prompts (UNECE R156
software update management compliance, rollback safety, fleet segmentation, repair-shop
workflows) → prioritize if >7 remain → confirm final list and next steps.

**Self-review:** no leading questions ("Wouldn't you agree that…" rephrased to "How do you
assess…"); every presented goal is grounded in the provided document — the R156 probe is
marked as a *suggestion*, not an existing goal; script fits the stated 45-minute slot.

## 4. E-commerce — plan a returns-management requirements workshop `[AI4RE-adapted]`

**Input:** "Half a day, hybrid. Participants: customer service leads, warehouse staff, shop
product owner, one finance controller. Goals: explore pain points in the returns process
and prioritize improvements for the new returns portal. I have never facilitated before."

**Output (abridged):** Overview table (objective, 4 h hybrid, deliverables: clustered pain
points + MoSCoW-prioritized improvement list) → preparation (pre-read: current returns
process map; Miro board with ready-made templates; explicit turn-taking rules for hybrid) →
timed agenda: welcome & goals (15 min) → process walkthrough (30) → silent brainwriting on
pain points (25 — chosen over open brainstorming because it needs little facilitation
experience and neutralizes the vocal customer-service group) → clustering & dot voting (30)
→ break → "How might we…" improvements (40) → MoSCoW on improvements (30) → wrap-up,
next steps, one-word check-out (20) → facilitation tips targeted at the stated dynamics
(warehouse staff historically quiet: address directly by name; finance controller may pull
toward cost detail: park on Parking Lot) → follow-up plan: photo/board synthesis same day,
summary to participants within 3 days, transfer into requirements log with traceability to
pain-point clusters.

**Why it is good:** techniques matched to a first-time facilitator (brainwriting, dot
voting — not conflict-mediation-heavy methods); real constraints (half-day, hybrid, group
dynamics) shape the agenda instead of a textbook full-day ideal; follow-up is a concrete
plan, not a footnote.
