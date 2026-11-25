# Examples — Elicitation Transcription

> **Provenance:** Example 1 condenses the worked examples from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. AI systems — transcribe a test-environment flipchart `[AI4RE]`

**Input:** photo of a hand-written flipchart from a workshop on test environments for
AI-based systems (guide example, provided by Silvia Linschi; generated with ChatGPT).

**Configuration:** AI's role: transcription expert for hand-written text in English ·
My role: requirements engineer who moderated a workshop on test environment · Image type:
hand-written · Format: structured text.

**Output shape (abridged):** structured transcription preserving the flipchart hierarchy —
title *"Test environment & AI-based SYS"* → section *"Why TE differ?"* (self-learning,
autonomy, multi-agency, explainability, hardware, big data, …) → section *"Usage of Virtual
TE? Scenarios"* with the icon-marked list (dangerous, unusual, extreme, time-intense,
observability & controllability, availability) → *Examples* (AI Habitat, Drive
Constellation, Matlab/Simulink). The AI closed by *offering* to normalize unclear phrases
("Manic non-determinism" → "Mainly non-deterministic") while keeping the structure.

**Why it is good:** layout hierarchy survived as nested structure; normalization was
offered as a separate confirmed step, not applied silently. **What to learn from its
flaw:** the misreading "Manic non-determinism" shipped unmarked — the skill instead marks
such items `[unclear: best guess "…"]`. (The guide's companion example for *Refine
Transcription* — an AIS-officer interview auto-transcribed with MS Word 365, then refined
with Copilot — shows the same pattern for audio: rules restated, user confirms, clean
speaker-labeled document delivered.)

## 2. Automotive — refine a brake-system interview transcript `[AI4RE-adapted]`

**Input (raw auto-transcript excerpt):** "speaker 1: so um when the the driver hits the
pedal uh what happens speaker 2: well the ECU it eh checks wheel speed sensors first no
wait actually first its the plausibility check erm of the pedal signal itself [crosstalk]
then wheel speeds"

**Output (refined):**
> **Interviewer:** When the driver hits the pedal, what happens?
> **Stakeholder:** The ECU checks the wheel speed sensors first — no, wait, actually first
> it's the plausibility check of the pedal signal itself. [inaudible — crosstalk] Then
> wheel speeds.

**Why it is good:** fillers ("um", "eh", "erm") removed, but the self-correction ("no,
wait, actually first…") is *kept* — it reveals safety-relevant ordering the stakeholder was
unsure about. Crosstalk marked `[inaudible]`; closing block flags it for audio review and
notes `Assumption: Speaker 2 is the brake-system engineer (introduced at 00:00, name
withheld)`.

## 3. Medical — transcribe a Miro screenshot from a ward-workflow workshop `[AI4RE-adapted]`

**Input:** screenshot from a Miro board (image type: `screenshot`, language: English,
subject: medication administration workflow) with three sticky-note clusters connected by
arrows.

**Output (excerpt):**
```
Medication Administration — Ward 4B (Miro board, frame "Current State")

Prescribe (cluster, yellow notes)
- Doctor enters order in HIS
- Verbal orders during night shift [unclear: note partially covered by cursor]

Prepare → Administer (arrow between clusters)
- Nurse double-check — "4-eyes" only if opioid
- Barcode scan skipped when scanner battery empty
```

**Why it is good:** cluster/arrow semantics preserved as structure (`A → B`); the covered
sticky note is marked, not guessed; the closing block recommends anonymization was
respected (no patient or staff names transcribed) and asks whether the red notes on frame
"Pain Points" should be transcribed too.

## 4. E-commerce — refine a remote-workshop transcript with attribution problems `[AI4RE-adapted]`

**Input:** 90-minute Teams auto-transcript of a checkout-redesign workshop; the tool
labeled all remote-room participants "Meeting Room 2".

**Output shape:** speaker-labeled transcript using role labels agreed with the user
(Facilitator, Product Owner, Payments Lead, "Meeting Room 2 — participant not
identifiable"); repeated vendor jargon ("PSP", "3DS challenge flow") preserved verbatim;
sections where two people talked over each other marked `[inaudible — overlapping
speech]`. Closing block: 7 turns listed with `[speaker uncertain]` for manual review, an
open question ("Was the 'drop guest checkout' remark serious or sarcastic? Tone is not
captured — check recording at ~00:41"), and the standard draft disclaimer.

**Why it is good:** attribution limits are surfaced instead of papered over; the sarcasm
note operationalizes the non-verbal-context pitfall; jargon survives untouched for the
downstream `requirements-extraction` step.
