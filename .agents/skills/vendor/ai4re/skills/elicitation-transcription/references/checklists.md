# Checklists — Elicitation Transcription

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* sections
> of the Transcribe cluster). Operationalized fidelity and process checks are
> `[Supplementary: IREB CPRE Glossary, GDPR]` where marked.

## 1. Transcript fidelity gate `[AI4RE-adapted]` (from the Refine Transcription rules)

Check the refined transcript; every "no" must be fixed or logged as an open question.

- [ ] **Verbatim wording** — no paraphrasing, no content change; only spelling, grammar,
      punctuation, filler removal and paragraphing were touched.
- [ ] **No summarization or interpretation** — every statement of the source is present in
      full; nothing condensed, merged or "explained".
- [ ] **Speaker labels present and consistent** — e.g. "Interviewer" / "Stakeholder";
      doubtful turns carry `[speaker uncertain]`.
- [ ] **Unclear segments marked** — `[inaudible]` / `[unclear]` used; no silent guessing.
- [ ] **Filler removal did not erase meaning** — hesitations, self-corrections or informal
      tone that signal stakeholder uncertainty are preserved or annotated. `[AI4RE]`
      (Language smoothing pitfall: smoothing may falsely suggest clarity or decisiveness).
- [ ] **Domain phrasing preserved** — technical terms, idioms and domain-specific wording
      kept as spoken; no normalization into generic vocabulary. `[AI4RE]`
- [ ] **Meaningful paragraphs** — structure follows topic shifts, not arbitrary breaks.

## 2. Speaker attribution review `[AI4RE]` (Audio quality pitfall)

- [ ] Overlapping speech, weak accents or unclear turn-taking flagged rather than resolved
      by guesswork.
- [ ] Statements attributed to the wrong stakeholder would distort requirements — every
      attribution is either certain or marked for manual review against the audio.
- [ ] Recommendation given (where relevant): review speaker labels manually; use
      diarization-capable tooling and good microphones for future sessions.

## 3. Non-verbal context review `[AI4RE]` (Implicit context pitfall)

- [ ] Reminder issued that tone, emphasis, hesitation, sarcasm, body language and power
      dynamics are not captured by the transcript.
- [ ] Observational notes or post-transcription annotations (e.g. mood, hesitation)
      recommended where interpretation of intent matters.
- [ ] No confidence, agreement or priority was *inferred* from wording alone.

## 4. Whiteboard transcription gate `[AI4RE-adapted]` (from the Whiteboard pitfalls)

- [ ] **Every visible element covered** — headings, bullets, side notes, legends; anything
      undecipherable is marked `[illegible]`, not dropped.
- [ ] **No invented words** — doubtful readings carry `[unclear: best guess "…"]`
      (the guide's own example misread "Mainly non-deterministic" as "Manic
      non-determinism" — expect such errors).
- [ ] **Layout reconstructed** — spatial groupings, columns, arrows and connections
      rendered explicitly (nesting, `A → B`); ambiguous arrangements flagged. `[AI4RE]`
      (Preserve layout context: AI is not very good at extracting spatial context).
- [ ] **Language stated** — the input language was specified before transcription; mixed
      languages flagged. `[AI4RE]` (Specify the language pitfall).
- [ ] **Image quality addressed** — skew, shadows or irrelevant regions that impaired
      reading are reported; cropping/retake recommended if quality blocked extraction.
      `[AI4RE]` (Enhance image quality pitfall).
- [ ] **Normalization only on request** — unclear phrases were transcribed faithfully
      first; cleanup offered as an explicit optional step.

## 5. Data protection check `[AI4RE]` `[Supplementary: GDPR]`

- [ ] User reminded (when context suggests external AI services): uploading audio/images
      to cloud services may violate GDPR or internal compliance policies and expose
      personal, strategic or confidential information.
- [ ] Mitigations named where relevant: local/offline tools (e.g. Whisper),
      GDPR-compliant and contractually bound providers, anonymization/pseudonymization
      before upload.
- [ ] Output itself contains no gratuitous personal data (e.g. replace full names with
      roles if the user agrees).

## 6. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Did I stay at transcription — no requirements derived, no statements overstated or
      "validated"? (Pitfall: LLMs may overstate or fabricate requirements not explicitly
      validated.)
- [ ] Vague or incomplete stakeholder statements flagged (e.g. `[unclear]`,
      `[incomplete thought]`) instead of completed?
- [ ] Domain or project context missing → did I ask for background notes and stakeholder
      roles rather than produce a generic result? `[AI4RE]` (Domain awareness pitfall).
- [ ] All assumptions prefixed `Assumption:`; all unclear passages listed at the end for
      review against the original audio/image?
- [ ] Is the output labeled a **draft** requiring expert review for correctness and
      contextual accuracy?
