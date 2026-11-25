---
name: elicitation-transcription
description: >
  Converts unstructured elicitation inputs into clean, structured, machine-readable
  artifacts according to the IREB AI4RE Prompt Guide (cluster "Transcribe"). Use when the
  user wants to refine a raw interview or workshop transcript (speaker labels, filler-word
  removal, paragraphing, verbatim fidelity) or to transcribe photos of whiteboards,
  flipcharts or digital-whiteboard screenshots into editable structured text. Triggers
  include: "clean up / refine this transcript", "interview transcript", "transcribe this
  recording", "whiteboard photo", "flipchart", "workshop notes", "Miro screenshot".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Elicitation
  ai4re-cluster: Transcribe
  ai4re-use-cases: [Refine Transcription, Transcribe Whiteboard Images]
---

# Elicitation Transcription

Turns raw elicitation output — interview recordings/transcripts and workshop artifacts such
as whiteboard or flipchart images — into clean, structured, machine-readable text that
downstream RE activities can work with.

## Provenance

`[AI4RE]` This skill implements the two use cases of the AI4RE Prompt Guide cluster
**Transcribe** (IREB core activity: *Elicitation*): *Refine Transcription* and *Transcribe
Whiteboard Images*. Workflows, templates and pitfalls originate from the guide.
`[Supplementary: IREB CPRE Glossary, GDPR]` Operationalized fidelity criteria and the data
protection checklist items are supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Refine a raw, machine-generated or hand-typed interview/workshop transcript: verbatim
  wording preserved, speaker labels added, spelling/punctuation corrected, filler words
  removed, text structured into paragraphs, unclear passages marked `[inaudible]`.
- Transcribe workshop artifacts (photo of a hand-written whiteboard or flipchart, or a
  screenshot from a digital collaboration tool such as Miro or Microsoft Whiteboard) into
  editable text that preserves the original structure.

**Do not use when:**
- The elicitation session still needs to be *prepared* (domain introduction, stakeholder
  identification, interview questions, workshop design) → `elicitation-preparation`.
- Requirements should be *identified* in the cleaned material → `requirements-extraction`.
- Individual requirements should be formulated, standardized or decomposed →
  `requirements-writing`.
- The artifact should be transformed into another representation (model, persona, test
  cases, plain language) → `requirements-translation`.
- The content should be checked against stakeholder intent → `requirements-validation`,
  or against quality criteria and contradictions → `requirements-verification`.
- The task concerns change impact (→ `change-impact-analysis`) or trace links
  (→ `requirements-traceability`).

This skill deliberately stops at *faithful transcription*. It does not interpret,
summarize or derive requirements — that is the extraction step.

## Roles

- **Claude acts as:** expert in transcribing stakeholder interviews for requirements
  engineering purposes (*Refine Transcription*), or transcription expert in reading and
  understanding hand-written text and digital artefacts in the input language
  (*Transcribe Whiteboard Images*) — role prompting per AI4RE.
- **Typical users:** requirements engineers and business analysts who conducted or
  moderated the interview/workshop; output must be usable as documentation and as input
  for requirements analysis.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Identify which use case applies (transcript refinement / image
   transcription). If both artifact types arrive together, process them separately and
   keep the outputs clearly labeled per source.
2. **Establish context.** Determine the language of the input, the elicitation subject,
   the speakers/roles involved and the desired output format. For images, determine the
   image type (hand-written vs. screenshot). `[AI4RE]` (configuration variables of both
   templates). If no artifact was provided, ask for it — never fabricate content.
3. **Sensitive-data check.** Interview recordings and whiteboard photos routinely contain
   personal and confidential information. If the context suggests the user might feed such
   data into external AI services, remind them to anonymize/pseudonymize first and to use
   GDPR-compliant or local tools. `[AI4RE]` (Data privacy pitfall).
4. **Clarify or assume.** Ask targeted questions when speaker attribution, language or
   image orientation is unclear. If proceeding anyway, prefix every guess with
   `Assumption:` (e.g. `Assumption: Speaker 2 is the stakeholder`).
5. **Execute** the use-case-specific procedure (below), applying the matching template
   from [references/templates.md](references/templates.md). Fidelity rule: never
   paraphrase, summarize or interpret; separate *transcribed from input* from anything
   inferred (e.g. expanded abbreviations, guessed words), and mark uncertain readings as
   `[inaudible]`, `[unclear]` or `[illegible: best guess "…"]`.
6. **Self-review.** Run the checklists from
   [references/checklists.md](references/checklists.md) against the output. Fix what
   fails; whatever cannot be fixed from the given input becomes an open question.
7. **Deliver.** Output in the requested format, followed by: assumptions, unclear/
   inaudible passages, open questions, and a one-line reminder that the result is a draft
   requiring review against the original recording/image by a human expert. `[AI4RE]`
   (general caution and conclusion sections of both use cases).

## Use cases

### 1. Refine Transcription `[AI4RE]`

Turn a raw interview transcript into well-readable, verbatim documentation.

1. Apply the guide's transcription rules exactly: keep the wording as spoken (only minor
   readability adjustments); add speaker labels (e.g. "Interviewer", "Stakeholder"); full
   sentences and standard punctuation where possible; mark unclear segments `[inaudible]`;
   never summarize or interpret; correct spelling/grammar; remove filler words and
   unnecessary repetitions; structure into meaningful paragraphs.
2. Watch the smoothing trade-off: removing fillers and hesitations may falsely suggest
   clarity or decisiveness. Where a hesitation or self-correction seems meaningful for
   requirements (uncertainty, resistance), keep it or annotate it (e.g.
   `[hesitation before answering]`). `[AI4RE]` (Language smoothing pitfall).
3. Preserve domain-specific phrasing; do not normalize technical terms into generic
   vocabulary. `[AI4RE]` (Domain awareness pitfall).
4. List all `[inaudible]`/`[unclear]` passages and doubtful speaker attributions at the
   end so the engineer can check them against the audio.

Template: *Refine Transcription* in [references/templates.md](references/templates.md).

### 2. Transcribe Whiteboard Images `[AI4RE]`

Extract editable, structured text from workshop images.

1. If no images are provided, ask for them; otherwise proceed. Rotate/interpret skewed
   images as needed. `[AI4RE]` (template task steps).
2. Extract hand-written text (image type *hand-written*) or rendered text (image type
   *screenshot*), in the stated language.
3. Return editable text that preserves the structure of the image: headings, lists,
   groupings, arrows/connections rendered as nested lists or `A → B` notation. Spatial
   layout carries meaning and is easily lost — reconstruct it explicitly and flag where
   the arrangement was ambiguous. `[AI4RE]` (Preserve layout context pitfall).
4. Mark illegible or doubtful readings `[illegible]` or `[unclear: best guess "…"]` —
   never silently invent words (the guide's own worked example contains a misreading,
   "Manic non-determinism" for "Mainly non-deterministic").
5. Offer, as a separate optional step, to normalize unclear phrases — only after the
   faithful transcription is delivered and only with the user's confirmation. `[AI4RE]`
   (worked example practice).

Template: *Transcribe Whiteboard Images* in
[references/templates.md](references/templates.md).

## Output formats

- **Refined transcript:** speaker-labeled dialogue (`**Interviewer:** … / **Stakeholder:**
  …`), meaningful paragraphs, `[inaudible]`/`[unclear]` markers; header block with
  interview metadata (date, subject, participants/roles) when known.
- **Whiteboard transcription:** structured text mirroring the image layout (headings,
  nested bullet lists, `A → B` for arrows), one section per image, image/source reference
  per section.
- **Closing block (always):** assumptions, unclear passages, open questions, draft
  disclaimer.
- Plain markdown unless the user requests another format (e.g. plain text, Word-ready
  text, CSV of extracted items). `[AI4RE]` (`[FORMAT]` variable).

## Quality gates

Check every deliverable against these criteria (operationalized in
[references/checklists.md](references/checklists.md)):

- **Fidelity** `[AI4RE]` — wording preserved; no paraphrase, summary or interpretation.
- **Completeness** `[AI4RE-adapted]` — every audible statement / visible element covered
  or explicitly marked as unclear; nothing silently dropped.
- **Attribution** `[AI4RE]` — speaker labels correct or flagged as uncertain.
- **Structure** `[AI4RE]` — paragraphs / layout reflect the source's organization.
- **Uncertainty marking** `[AI4RE]` — `[inaudible]`, `[unclear]`, `[illegible]` used
  instead of guesses.
- **Data protection** `[AI4RE]` `[Supplementary: GDPR]` — sensitive-data reminder given
  where relevant.

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- Fidelity scan: sample passages against the input — is any content paraphrased,
  reordered, summarized or "improved" beyond spelling/punctuation/filler removal?
- Fabrication scan: does the output contain any word, label or list item not supported by
  the input? Every non-input-derived element must be marked `Assumption:` or `[unclear]`.
- Attribution scan: are all speaker labels consistent and plausible; are doubtful turns
  flagged?
- Smoothing scan: did filler removal erase a meaningful hesitation, self-correction or
  informal tone that signals stakeholder uncertainty? (Pitfall: false decisiveness.)
- Structure scan: does paragraphing/layout reconstruction match the source; are ambiguous
  spatial groupings flagged?
- Boundary scan: did I stay at transcription and avoid deriving requirements or
  interpretations? (That belongs to `requirements-extraction`.)

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing either use case |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting templates to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
