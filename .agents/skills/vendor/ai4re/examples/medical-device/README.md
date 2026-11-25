# Scenario: Infusion Pump — Specification Audit + Stakeholder Validation (W3 → W6)

**Domain:** medical devices (IEC 62304 context) · **Skills:** 4

## The request

> "Our infusion pump spec has grown for three years. Audit it, then make the alarm
> handling reviewable for the clinical advisory board."

## Master classification & plan

**W3** (spec quality audit) followed by **W6** (stakeholder validation round) scoped to
the alarm-handling chapter. Central clarification: normative context (IEC 60601-1-8 for
alarms?), audience of the validation round (clinicians, non-technical). Confidentiality
reminder for the regulated spec.

## Walkthrough (abridged artifacts)

**1. Synonym table — `requirements-writing`**
Detects safety-relevant terminology drift: "alarm" / "alert" / "notification" used
interchangeably — flagged as **not** mergeable (IEC 60601-1-8 distinguishes alarm
priorities from information signals); "occlusion" fixed as primary term over "blockage".

**2. Consistency analysis — `requirements-verification`**
Findings grouped by type: conflict (audio-paused state vs. "audible alarm at all times"),
version drift (two bolus-limit values), implied gap (no requirement for alarm behavior
during battery swap). Each with a 2–3 sentence improvement suggestion. False-positive
scan: dosage requirements at system vs. component level are *not* duplicates —
abstraction levels annotated first.

**3. Repair — `requirements-writing`**
Defective requirements reformulated (ISO 29148 style, testable); the battery-swap gap
becomes an open question for the safety board — no invented behavior in a safety context.

**4. Plain language — `requirements-translation`** (Explain in Simple Language)
Thematic summary for clinicians: what the alarm system does and why, "What this means
for you:" per theme; obligation levels strictly preserved (no "must" → "should"), IEC
terms explained rather than deleted.

**5. Wireframe — `requirements-validation`**
Self-contained HTML wireframe of the alarm screen states (normal / occlusion alarm /
audio-paused): red "Ref:" tags per requirement, yellow-marked assumptions (max 5), empty/
loading/error states included, two alternative interpretations for the ambiguous
"escalation view" requirement — for the board to decide, not the AI.

## Consolidated deliverable

Audit report (findings + fixes + open safety questions), harmonized terminology, clinical
summary, annotated wireframe walkthrough kit. Draft label + explicit note: consistency ≠
correctness — clinical and regulatory review mandatory.
