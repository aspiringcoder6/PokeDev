# Prompt Patterns — Elicitation Transcription

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates and worked
> examples of the Transcribe cluster. Pattern names follow common prompt-engineering
> vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Both templates: "AI's role" (transcription expert) + "User's/My role" (requirements engineer who conducted/moderated the session) | Adopt the expert persona *and* model the requester's perspective; the output serves RE documentation, not general note-taking |
| **Purpose priming** | "Purpose:" line states the end state (well-readable documentation; transcription of workshop artifacts) before the task | Keep the documentation goal in view — readable *and* faithful, not merely converted |
| **Explicit rule list** (constraint prompting) | Refine Transcription: nine numbered transcription rules | Enumerate hard constraints instead of describing intent; every rule is checkable, deviations are defects |
| **Fidelity constraint** (strict grounding) | "Do not paraphrase or change the content in any way"; "Do not summarize or interpret statements" | Wording is data — preserve it; only spelling, punctuation, fillers and paragraphing may change |
| **Uncertainty marking** | "If a segment is unclear or inaudible, mark it as [inaudible]" | Prefer an explicit marker over a plausible guess; collect all markers at the end for human review |
| **Conditional branching** | Whiteboard template: "If no images are provided … ask"; "If image type is hand-written, extract hand-written text; otherwise …" | Encode explicit if/else in procedures instead of guessing what the input is |
| **Missing-input guard** (ask-before-proceed) | Whiteboard step 1: request the images if absent | Never fabricate content for an absent artifact; a clarifying question is the correct output |
| **Language priming** | `[LANGUAGE]` variable: state the input language up front | Models transcribe better when the language is known; ask if mixed or unstated `[AI4RE]` (Specify the language tip) |
| **Context anchoring** | `[SUBJECT]` variable: name the workshop topic | Domain context disambiguates handwriting and jargon; ask for background notes and stakeholder roles when missing |
| **Structure preservation** | "Return editable text preserving the structure of the text in the images" | Reconstruct layout explicitly (headings, nesting, `A → B` for arrows); flag ambiguous spatial groupings |
| **Output format constraint** | `[FORMAT]` variable; "Format: Structured text" | Fix the target format before generating |
| **Two-phase refinement** (faithful-then-normalize) | Worked example: ChatGPT offers "Would you like me to normalize … while keeping the structure?" *after* delivering the transcription | Deliver the faithful transcription first; offer normalization/cleanup as a separate, user-confirmed step |
| **Plan-confirm-execute** | Refine worked example: Copilot first summarizes the rules it will apply and the next step, then produces the document after user confirmation | For long inputs, restate the applicable rules and let the user confirm before processing |
| **Privacy guard** | Pitfalls: GDPR, cloud upload of audio | Remind users to anonymize/pseudonymize and prefer local or compliant tools before sensitive material is uploaded |
| **Draft-not-decision** | Conclusions of both use cases: "expert review ensures correctness and contextual accuracy/completeness" | Label output as draft; require review against the original recording or image |
