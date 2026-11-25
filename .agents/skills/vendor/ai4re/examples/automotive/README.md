# Scenario: Automotive ADAS ECU — Legacy Reverse Engineering + Change (W5 → W4)

**Domain:** automotive / embedded · **Process:** V-model context · **Skills:** 5

## The request

> "The lane-keep-assist ECU code is the only up-to-date documentation. We need a spec —
> and then we have to assess a change request: new lane-marking sensor."

## Master classification & plan

Two chained workflows: **W5** (legacy → spec), then **W4** (change management) on the
recovered baseline. Central clarification: which code modules are in scope, ASIL level,
existing architecture documents? Sensitive-data reminder: proprietary ECU code should not
go to external AI services without approval.

## Walkthrough (abridged artifacts)

**1. Requirements from code — `requirements-translation`**
Structured spec from the C modules: functional requirements (lane detection, steering
torque request, driver override), NFRs only where the code shows them (watchdog timing,
CRC checks) — "no NFRs for thermal limits derivable from code" stated, not invented.
Every scope-exceeding statement marked `Assumption:`; traceability note maps requirement →
module/function.

**2. Standardization — `requirements-writing`**
Recovered requirements reformulated in EARS ("While lane-keep assist is active, when
lateral deviation exceeds [X] m, the ECU shall …"); missing values flagged as open
questions for the safety team — no invented thresholds.

**3. Closing the loop — `requirements-verification`** (Compare Specification With Source Code)
Discrepancy table Match/Partial/Missing/Extra: driver-override timeout implemented but
undocumented (Extra → spec update), documented sensor plausibility check not visible in
provided files (Partial with caveat, not Missing).

**4. Trace links — `requirements-traceability`**
Trace matrix requirement ↔ module ↔ test; tags: ASIL, component, safety-relevance.

**5. Change impact — `change-impact-analysis`**
CR "replace camera-only lane detection with camera+lidar fusion" decomposed into atomic
changes; six-column impact table over the recovered baseline: affected requirements
(detection latency, plausibility checks), artifacts (interface spec, DBC file), owners
(perception team, safety engineer), risks (recertification), missing artifact detected
(no sensor-fusion architecture doc → proposed with owner).

## Consolidated deliverable

Recovered + verified specification, trace matrix, impact report with edit points and
validation checklist. Safety-critical caveat prominent: all thresholds and ASIL
classifications require confirmation by the functional safety team (draft label).
