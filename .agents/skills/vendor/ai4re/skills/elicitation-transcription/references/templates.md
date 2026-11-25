# Templates — Elicitation Transcription

> **Provenance:** `[AI4RE]` All templates below originate from the IREB AI4RE Prompt Guide,
> cluster *Transcribe* — pages [Transcribe (cluster)](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2667249678),
> [Refine Transcription](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043424),
> [Transcribe Whiteboard Images](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/pages/2314043407).
> Wording is preserved; formatting is adapted for skill use. Sections marked
> `[Supplementary: …]` are additions from other standards.

All templates follow the AI4RE configuration anatomy: **AI's role · User's/My role ·
Purpose · Task · Format · Input**. Resolve every `[VARIABLE]` before use — either from the
user's request or by asking.

---

## 1. Refine Transcription `[AI4RE]`

**Purpose:** Turn a raw stakeholder-interview transcript into well-readable, verbatim
documentation.

```
AI's role: expert in transcribing stakeholder interviews for requirements engineering
purposes
User's role: requirements engineer
Purpose: Getting well-readable documentation of the interview.

Task: Transcribe the interview accurately and verbatim, following these rules:
- Do not paraphrase or change the content in any way. The wording should remain exactly
  as spoken, with only minor adjustments for readability.
- Include speaker labels (e.g., "Interviewer", "Stakeholder").
- Use full sentences and standard punctuation where possible.
- If a segment is unclear or inaudible, mark it as [inaudible].
- Do not summarize or interpret statements, the original wording must be preserved.
- Correct spelling and grammar errors.
- Remove filler words and unnecessary repetitions.
- Add proper punctuation.
- Structure the text into meaningful paragraphs.

Format: [FORMAT]
Input: [TRANSCRIPTION]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[FORMAT]` | Output format, e.g. `plain text`, `word` |
| `[TRANSCRIPTION]` | The raw transcript to refine (the guide's "+ Add transcription") |

**Notes from the guide** `[AI4RE]`: the worked example refined an interview with an AIS
officer that had been auto-transcribed with MS Word 365; speaker labels were normalized to
"Interviewer" and "Stakeholder". Balance the rules "do not paraphrase" and "remove filler
words" carefully — see the *Language Smoothing and Over-Correction* checks in
[checklists.md](checklists.md).

---

## 2. Transcribe Whiteboard Images `[AI4RE]`

**Purpose:** Extract editable, structure-preserving text from workshop images (whiteboard/
flipchart photos or digital-whiteboard screenshots).

```
AI's role: Transcription expert in reading and understanding hand-written text and digital
artefacts in [LANGUAGE].
My role: Requirements engineer who has moderated a workshop on [SUBJECT].
Purpose: I want to get the transcription of the provided workshop artifacts (images).
Image type: [IMAGE TYPE]

Task:
- If no images are provided with this prompt, ask for the images; otherwise omit this step.
- Rotate provided images, if necessary.
- If image type is hand-written, extract hand-written text; otherwise extract text.
- Return editable text preserving the structure of the text in the images.

Format: Structured text
Input: [IMAGES]
```

| Variable | Meaning / typical values |
|----------|--------------------------|
| `[LANGUAGE]` | Language of the input text, e.g. `English` |
| `[SUBJECT]` | Subject of the workshop |
| `[IMAGE TYPE]` | Type of workshop result — e.g. a photo of a hand-written flip chart or whiteboard, or a screenshot from a digital collaboration tool such as Miro or Microsoft Whiteboard: `hand-written` or `screenshot` |
| `[IMAGES]` | The workshop images to transcribe (the guide's "+ Add transcription") |

**Tool note from the guide** `[AI4RE]`: five LLM-based tools were tested for this use case
(ChatGPT-4o, Claude Sonnet 4, Mistral "Le Chat", Google Gemini 2.5, Microsoft Copilot 365);
as of June 2025 only ChatGPT-4o (paid) produced usable results. Capabilities evolve —
verify output quality per tool rather than assuming it.

**Practice from the guide's worked example** `[AI4RE-adapted]`: after delivering the
faithful transcription, *offer* to normalize unclear phrases (e.g. "Manic non-determinism"
→ "Mainly non-deterministic") while keeping the structure — normalization only happens with
explicit user confirmation, never silently.

---

## Uncertainty markers `[Supplementary]`

Consistent markers for both use cases (extending the guide's `[inaudible]`):

| Marker | Use for |
|--------|---------|
| `[inaudible]` | Audio segment that cannot be understood `[AI4RE]` |
| `[unclear: best guess "…"]` | Doubtful reading with a candidate interpretation |
| `[illegible]` | Handwriting that cannot be deciphered |
| `[speaker uncertain]` | Turn whose speaker attribution is doubtful |
| `Assumption: …` | Any inference not directly supported by the input |
