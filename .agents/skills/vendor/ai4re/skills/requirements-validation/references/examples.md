# Examples — Requirements Validation

> **Provenance:** Example 1 condenses the worked example from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. School app — wireframe for parents `[AI4RE]`

**Configuration (from the guide's filled template):** AI's role: Expert in Requirements
Engineering with expertise in UI/UX · My role: Requirements Engineer · My purpose:
Validation of requirements with stakeholders with the help of wireframes · System: school
app · Domain: school · Target group: parents · Application type: mobile · Rules: derivation
+ navigation only (optional rules 3–6 deleted) · Input: requirements as sole source of
truth · Language: English · Style: sketch · Format: one self-contained HTML file (embedded
CSS, no external libraries), clearly separated sections per screen. Generated with Claude
Sonnet 4.6.

**Output shape:** one HTML file, one section per screen derived from the parent-facing
requirements; sketch styling; no navigation beyond what the requirements explicitly
support.

**Why it is good:** minimal configuration shows the core discipline — screens strictly
derived, no invented menus — so the stakeholder discussion stays on the requirements, not
on information architecture.

## 2. Medical — infusion pump status screen for ward nurses `[AI4RE-adapted]`

**Input (sole source of truth):** three requirements: *US-1* "As a ward nurse, I want to
see the remaining infusion time and volume per pump, so that I can plan bag changes." ·
*US-2* "As a ward nurse, I want an occlusion alarm to be visually distinguishable from all
other notifications." · *US-3* "The system shall let the nurse acknowledge an alarm; the
acknowledgment shall be logged."

**Configuration:** System: infusion pump monitoring app · Domain: hospital ward · Target
group: ward nurses · Type: mobile · Rules 1–6 active · Style: technical.

**Output (markdown wireframe, abridged):**

```
┌─ Pump Overview ──────────────────────────────┐
│ Pump 3 — Bed 12            (Ref: US-1)       │
│  Remaining: 42 min · 105 ml (Ref: US-1)      │
│ Pump 5 — Bed 14            (Ref: US-1)       │
│  ▓▓ OCCLUSION ALARM ▓▓     (Ref: US-2)       │
│  [ Acknowledge ]           (Ref: US-3)       │
├─ [STATE: empty]   No pumps assigned          │
├─ [STATE: loading] Fetching pump data…        │
├─ [STATE: error]   Connection to pump lost    │
└──────────────────────────────────────────────┘
```

`Assumption:` (1) one overview screen lists all pumps assigned to the nurse — no
requirement defines the grouping. `[AMBIGUITY]` US-2 "visually distinguishable" —
interpretation A: distinct color + icon; interpretation B: full-screen takeover. Both
sketched; stakeholders decide. **Not included:** patient master data, alarm history — not
in the input.

**Why it is good:** the safety-critical ambiguity (how prominent must an occlusion alarm
be?) becomes a concrete stakeholder decision instead of a silent design choice; no
navigation invented (no menu, no dashboard beyond the one derived screen).

## 3. Banking — payment approval flow for corporate customers `[AI4RE-adapted]`

**Input (sole source of truth):** *R-10* "The system shall present pending payments to the
approver with amount, beneficiary and initiator." · *R-11* "When approving a payment above
EUR 10,000, the system shall require a second approver." · *R-12* "The approver shall be
able to reject a payment with a mandatory reason." A retail-banking style guide is provided
**as visual direction only**.

**Output (mockup description, abridged):** Screen *Pending approvals* — list rows with
amount, beneficiary, initiator (Ref: R-10); row action *Approve* → if amount > EUR 10,000,
confirmation panel "Second approver required — request sent" (Ref: R-11); row action
*Reject* → modal with mandatory reason field, submit disabled while empty (Ref: R-12).
Empty/loading/error states per screen (yellow). `Assumption:` approvals and rejections
return to the list view. **Deliberately excluded:** the style guide's hamburger menu and
global search — present in the screenshots, supported by no requirement; noted as
illustrative only.

**Why it is good:** demonstrates the style-contamination defense — visual direction shaped
colors and spacing, but its structural patterns were rejected and the rejection was made
explicit to stakeholders.

## 4. Automotive — EV charging planner HMI `[AI4RE-adapted]`

**Input (sole source of truth):** a UI specification (not requirements): screen *Charge
Planning* with elements route map, list of charging stops (name, connector type, planned
charge %), and per-stop action *Skip stop*; plus a note "driver must confirm any plan
change while driving".

**Configuration:** System: in-vehicle charging planner · Domain: automotive/EV · Target
group: drivers · Type: embedded HMI (agreed deviation from mobile/web — confirmed with the
user) · Rules 1–6 active · Style: technical.

**Output (ASCII wireframe, abridged):**

```
┌─ Charge Planning ────────────────────────────────┐
│ [ route map area ]              (Ref: UI-spec §2)│
│ Stop 1  IONITY A8 · CCS · 80%   (Ref: UI-spec §3)│
│         [ Skip stop ]           (Ref: UI-spec §3)│
│ ▓ Confirm change? While driving, plan changes    │
│   require driver confirmation.  (Ref: note §4)   │
│ [STATE: empty]   No charging stops planned       │
│ [STATE: loading] Calculating charging plan…      │
│ [STATE: error]   Charging network data offline   │
└──────────────────────────────────────────────────┘
```

`[AMBIGUITY]` "confirm any plan change while driving" — interpretation A: modal blocking
the whole screen; interpretation B: inline banner with confirm button (less distracting).
Flagged for validation with drivers and a distraction-guideline expert. `Assumption:`
skipping a stop is a "plan change" and therefore triggers confirmation (max-5 budget: 1
used). **Not included:** settings, trip history, any menu — not in the UI specification.

**Why it is good:** shows the UI-specification input variant; the driver-distraction
ambiguity is exactly what a stakeholder validation session must decide, and the wireframe
makes it discussable.
