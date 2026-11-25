# Examples — Requirements Extraction

> **Provenance:** Example 1 condenses the worked example from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. Aviation — identify requirements from an interview transcript `[AI4RE]`

**Input:** transcribed audio recording — an interview about the AIS (Aeronautical
Information Services) officer role: information dissemination, quality assurance, stress
handling, security, teamwork.

**Configuration:** the AI4RE template as-is; two-column table, user story format.

**Output shape (abridged):** one-line summary → table of ~20 user stories, each with a
verbatim quote, e.g.:

| Requirement | Reference |
|---|---|
| As an AIS officer, I want to ensure that all relevant stakeholders (pilots, ATC, etc.) receive the necessary information in a timely manner, so that flight operations remain safe and smooth. | "Make sure everyone has the information at the time. Pilots, air traffic control, everyone to keep things smooth and safe." |
| As an AIS officer, I want to validate information before publication using quality assurance methods (cross-checks, checklists, peer review), so that errors with potentially serious consequences are avoided. | "How do you ensure the accuracy and quality of aeronautical information? … Do you cross-reference information with multiple sources? … Because mistakes can have serious consequences." |

→ *Recommendation:* validate with stakeholders and prioritize (MoSCoW); refine QA,
security/compliance and dissemination candidates with acceptance criteria and KPIs (time to
publication, first-time-right rate, SLA compliance); add organization-specific systems
(e.g., AIM databases) as non-functional requirements. Offered follow-ups: prioritized
backlog with acceptance criteria, functional vs. non-functional mapping.

**Why it is good:** every candidate is traceable to a quote (some cite multiple passages);
duplicates are merged; the closing recommendation routes the draft into validation and
refinement instead of presenting it as final.

## 2. Automotive — workshop notes on a parking assistant `[AI4RE-adapted]`

**Input:** bullet-point notes from a feature workshop: "customers complain parking sensors
beep too late in tight garages — braking must kick in earlier"; "OEM wants camera + ultrasonic
fusion"; "legal said UNECE R79 limits steering intervention"; "ops: over-the-air update path
unclear".

**Output (extended table, excerpt):**

| ID | Requirement | Reference | Type | Topic | Notes |
|---|---|---|---|---|---|
| R1 | As a driver, I want the parking assistant to warn and brake earlier in confined spaces, so that low-speed collisions are avoided. | "parking sensors beep too late in tight garages — braking must kick in earlier" | functional | Collision avoidance | "earlier" unquantified → open question: target reaction distance/time |
| R2 | The parking assistant shall fuse camera and ultrasonic sensor data. | "OEM wants camera + ultrasonic fusion" | functional + constraint (flagged) | Sensing | Stakeholder-mandated solution — record as constraint, verify intent |
| R3 | Steering intervention shall comply with UNECE R79. | "legal said UNECE R79 limits steering intervention" | constraint | Compliance | Regulatory — extracted as declarative statement, not a user story; route to `requirements-writing` |

→ *Gaps:* no quality requirements elicited (availability, false-positive rate); OTA update
need mentioned but no requirement stated — open question. *Interdependency:* R1 depends on
R2's sensor fusion latency.

**Why it is good:** regulatory candidate escapes the user story template (pitfall handled);
a solution mandate is flagged as constraint instead of laundered into a need; gaps are
named, not filled.

## 3. E-commerce — stakeholder email thread `[AI4RE-adapted]`

**Input:** email thread between marketing, support and a key account: marketing wants
"guest checkout, our funnel dies at registration"; support reports "customers can't find
where to enter voucher codes, tickets pile up every campaign"; key account asks for
"invoices as PDF, our accounting rejects the current text mails"; marketing later replies
"but we still need emails for remarketing".

**Output (two-column table, excerpt):**

| Requirement | Reference |
|---|---|
| As a shopper, I want to check out as a guest without creating an account, so that I can complete my purchase without friction. | "guest checkout, our funnel dies at registration" |
| As a shopper, I want a clearly visible voucher code field in checkout, so that I can redeem campaign codes without contacting support. | "customers can't find where to enter voucher codes, tickets pile up every campaign" |
| As a business customer, I want invoices as PDF documents, so that my accounting can process them. | "invoices as PDF, our accounting rejects the current text mails" |

→ *Contradiction flagged:* guest checkout vs. "we still need emails for remarketing" — open
question: is an email address mandatory in guest checkout, and under which consent
(GDPR)? *Pattern:* two of three stakeholders describe checkout friction — candidate theme
for prioritization.

**Why it is good:** the conflict between two extracted candidates is surfaced as an open
question instead of silently resolved; a cross-stakeholder pattern is reported.

## 4. AI systems — user interview on an ML document classifier `[AI4RE-adapted]`

**Input:** interview with a claims department lead about an ML-based classifier for
incoming insurance documents: "if the model isn't sure, a human has to look at it — we
can't auto-reject claims"; "the auditors will ask why a document was routed somewhere";
"anything above ninety-five percent of today's manual accuracy would already help";
"retraining shouldn't need our IT every time".

**Output (excerpt):**

| Requirement | Reference |
|---|---|
| As a claims department lead, I want documents with low classification confidence routed to manual review, so that no claim is auto-rejected without human judgment. | "if the model isn't sure, a human has to look at it — we can't auto-reject claims" |
| As an auditor, I want the routing decision for each document to be explainable and logged, so that classifications can be justified retrospectively. | "the auditors will ask why a document was routed somewhere" |
| As a claims department lead, I want classification accuracy of at least 95% of today's manual baseline, so that the system reduces workload without increasing errors. | "anything above ninety-five percent of today's manual accuracy would already help" |

→ `Assumption:` "isn't sure" = a confidence threshold to be defined with the stakeholder —
the input gives no number; the candidate must not invent one. *Gap:* no statements on
training data, bias handling or model monitoring — open questions for a follow-up session
(recommend `elicitation-preparation`). *Note:* the 95% figure is relative to an unmeasured
manual baseline — flag baseline measurement as a prerequisite.

**Why it is good:** quantification stays exactly as vague as the stakeholder left it, with
the missing threshold flagged instead of guessed; AI-specific gaps (explainability given,
bias/monitoring absent) are detected because the whole input was read against the domain.
