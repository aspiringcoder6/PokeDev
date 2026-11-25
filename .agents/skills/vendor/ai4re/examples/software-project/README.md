# Scenario: SaaS Fleet Management — Greenfield (Workflow W1)

**Domain:** software / SaaS · **Process:** classic + iterative · **Skills:** 6

## The request

> "We're building a fleet management platform for e-scooter operators. Help me get from
> nothing to a first reviewed specification."

## Master classification & plan

`ai4re-master` classifies: broad greenfield → **W1**. No elicitation material exists yet,
so the plan splits into a pre-elicitation phase (steps 1–3) and a post-elicitation phase
(steps 4–8). Central clarification round: target market (EU cities?), B2B/B2C, preferred
formulation standard (answer: user stories, INVEST), regulatory scope.

## Walkthrough (abridged artifacts)

**1. Domain briefing — `elicitation-preparation`** (Introduce a New Domain)
Five artifacts: Introduction, System Context, Regulations and Standards (city licensing,
GDPR for location data — `Assumption:` EU market, listed separately), Actors, Glossary.

**2. Stakeholders — `elicitation-preparation`** (Identify Stakeholders)
Table with Onion Model layers: operations manager (core), mechanics, city authorities
(wider environment), riders, insurers. Priorities + assumptions block.

**3. Interview guides — `elicitation-preparation`** (Prepare Interview)
Timed exploratory guide for the operations manager; goal-confirmation guide converging on
3–7 main goals for the product sponsor.

**4. Transcript refinement — `elicitation-transcription`** (after real interviews)
Speaker-labeled verbatim transcript, `[inaudible]` markers, no smoothing; GDPR reminder
for the recording upload.

**5. Extraction — `requirements-extraction`**
Candidate table — every candidate with a verbatim quote reference; gaps surfaced ("no
statement on battery-swap logistics" → open question, not invented).

**6. Writing — `requirements-writing`**
Synonym table first ("vehicle" vs. "scooter" vs. "asset" → primary term fixed), then
INVEST user stories with Given/When/Then acceptance criteria; vague candidates
("dashboard should be fast") reformulated measurably or escalated as questions.

**7. Verification — `requirements-verification`**
Pairwise consistency findings: conflict between offline-capability story and
real-time-tracking NFR → improvement suggestion → fixed via step 6.

**8. Traceability — `requirements-traceability`**
Tags (component, MoSCoW, risk) + trace matrix: interview statement → candidate → story ID.

## Consolidated deliverable

Specification draft + glossary + trace matrix + consolidated assumptions (4), open
questions (6, incl. two for the city authority), risks (2). Draft label + recommended
next activities (validation workshop, wireframes via `requirements-validation`).
