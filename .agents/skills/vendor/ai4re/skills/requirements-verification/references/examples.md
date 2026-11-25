# Examples — Requirements Verification

> **Provenance:** Examples 1–2 condense the worked examples from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 3–5 are new, following the same method `[AI4RE-adapted]`.

## 1. Library system — analyze requirements consistency `[AI4RE]`

**Input:** a library-system specification (user stories US1–US16 plus use cases)
extended with new requirements related to existing ones.

**Output shape (abridged, grouped by relationship type):**
- *Conflicts:* `US6.7` "The system must calculate and apply fines solely based on
  predefined policies, without any mechanism for manual adjustments." vs. `US6.6`
  "Staff can reduce or waive fines with proper authorization." — **Conflict — Direct
  contradiction**; suggestion: decide between strict automation and audited overrides,
  define the policy once.
- *Similarity/Duplication:* `US4.7` "Overdue items restrict new checkouts until
  resolved." vs. `US6.4` "Accounts with overdue items cannot borrow new materials." —
  **Exact functional duplication**; merge into one business rule reused via
  traceability links.
- *Dependencies:* eligibility check `US4.1` misses the verification-status condition
  implied by `US2.6` — extend and centralize eligibility validation.
- *Terminology:* account status model (Active/Suspended/Expired) vs. a "Verified"
  status — separate account status from verification status.
- *Test/Quality misalignment:* two lockout rules (password vs. passkey, both "5 failed
  attempts within 15 minutes") — clarify shared vs. separate counters.
- *Completeness & implied gaps:* timestamp-based queueing vs. automatic priority
  advancement — the interaction rule is missing; define deterministic ordering.

**Why it is good:** every pair quoted exactly with IDs; each pair in exactly one
category with a named subtype; suggestions are pair-specific and explain why the fix
matters; gaps *between* requirements surfaced, not just pairwise contradictions.

## 2. CRM system — check model consistency (class vs. sequence diagram) `[AI4RE]`

**Input:** PlantUML class diagram (`Customer`, `Order`, `Invoice`, `OrderService`,
`OrderStatus` enum, lifecycle note "Cancellation is only allowed before SHIPPED") and a
sequence diagram of order placement.

**Findings (abridged, each with Finding / Impact / Suggestion citing exact element
names):**
- Naming: participant `Client` vs. class `Customer`; actor `SalesAgent as User` absent
  from the class model; `createOrder(...)` vs. message `placeOrder(...)` vs.
  association label `places >` — pick canonical names, align both diagrams.
- Signatures: `sendInvoice(orderId : int)` in the sequence vs.
  `sendInvoice(orderId : String)` in the class diagram (and `Order.id : String`) —
  standardize the type everywhere.
- Multiplicity vs. behavior: two `sendInvoice` calls for one order vs.
  `Order "0..1" --> "1" Invoice` — make the operation idempotent or change the
  multiplicity.
- Lifecycle: `cancelOrder` sent after `shipOrder` violates the note's rule — reorder
  the interaction or update the constraint.
- Boundary: unused `participant Client`; unclear whether `SalesAgent` is external actor
  or domain class.

**Why it is good:** diagram types identified first, elements parsed per UML metamodel,
findings cite exact element names only, and every suggestion branches on modeling
intent ("if same concept, rename; if different, add the class and its relation").

## 3. Automotive — model consistency for a door-lock ECU `[AI4RE-adapted]`

**Input:** state machine diagram of a central-locking ECU (states `UNLOCKED`,
`LOCKED`, `SECURED`; transition note "SECURED reachable only from LOCKED with valid key
fob") and a sequence diagram of the crash-unlock scenario.

**Findings (abridged):**
- State mismatch: sequence diagram message `enterSafeMode()` targets a state
  `SAFE_MODE` that does not exist in the state machine (`UNLOCKED`/`LOCKED`/`SECURED`
  only) — add the state with entry/exit transitions or rename to an existing state.
- Transition violation: crash event triggers `unlockAll()` directly from `SECURED`,
  but the state machine defines no `SECURED → UNLOCKED` transition — safety-relevant;
  add the crash-triggered transition explicitly rather than assuming it.
- Actor mismatch: sequence uses `CrashSensor`, state machine note says "airbag control
  unit signal" — clarify whether these are the same signal source.
- `Assumption:` both diagrams describe the same ECU variant (no market-specific
  derivate) — confirm.

**Why it is good:** static lifecycle constraints checked against dynamic behavior; the
safety-critical finding is flagged for expert review instead of being "fixed" silently.

## 4. Medical device — requirements consistency in an infusion pump spec `[AI4RE-adapted]`

**Input:** 40 requirements for an infusion pump, merged from two document versions.

**Output (abridged):**
- **Conflict — numeric/value:** `REQ-012` "Occlusion alarm shall trigger within 30
  seconds at flow rates ≥ 1 ml/h." vs. `REQ-031` "The pump shall signal occlusion
  within 2 minutes at all flow rates." — harmonize thresholds; the stricter bound is
  likely intended for high flow rates only.
- **Terminology — mismatch:** "alarm" vs. "alert" vs. "notification" used for the same
  occlusion event — safety-relevant under IEC 60601-1-8 priority semantics; map terms
  to alarm priorities before merging.
- **Version drift:** `REQ-007` references "IFU rev. C" while `REQ-029` references
  "IFU rev. E" — update to the current controlled document.
- **Implied gap:** `REQ-018` (auto-restart after transient fault) + `REQ-022` (bolus
  delivery requires confirmation) together leave restart-during-bolus undefined — add
  a companion requirement.
- Closing: consistency ≠ correctness — a harmonized 2-minute alarm limit may still be
  clinically wrong; clinical/regulatory SME review required.

**Why it is good:** value, terminology, version and gap categories all exercised; the
report separates what the documents say from what a domain expert must decide.

## 5. Cloud / microservices — compare specification with source code `[AI4RE-adapted]`

**Input:** API specification (12 requirements) for a payment-orchestration
microservice plus `payment_service.py`, `retry.py`, and the OpenAPI file.

**Output (abridged discrepancy table):**

| Specification Item | Code Reference | Match Status | Explanation |
|---|---|---|---|
| REQ-03: Retry failed captures max 3 times with exponential backoff | `retry.py – @retry(max_attempts=5)` | Partial | Retry implemented, but 5 attempts instead of 3; backoff base not configurable as specified |
| REQ-05: Idempotency key required on POST /payments | `payment_service.py – create_payment()` | Missing | No idempotency-key header handling found in the provided files |
| REQ-09: All amounts processed in minor units (cents) | `payment_service.py – Decimal(amount)` | Partial | Decimal used, but unit convention not enforced or documented; risk of major/minor unit mix-up |
| — (unspecified) | `payment_service.py – auto_refund_on_timeout()` | Extra | Automatic refund behavior implemented but absent from the specification — specify or remove |

Summary: 6 Match · 3 Partial · 2 Missing · 1 Extra. Caveats: authentication middleware
and rate limiting live outside the provided files — marked Partial, not Missing; the
availability NFR (99.9%) is unverifiable from code alone.

**Why it is good:** "Extra" behavior surfaced, not just gaps; context limits disclosed
honestly; every verdict tied to a concrete file and element.
