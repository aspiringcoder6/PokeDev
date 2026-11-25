# Examples — Requirements Writing

> **Provenance:** Example 1 condenses the worked examples from the AI4RE Prompt Guide
> `[AI4RE]`. Examples 2–4 are new, following the same method `[AI4RE-adapted]`.

## 1. Aviation — decompose a NOTAM query requirement `[AI4RE]`

**Input (high level):** "As a third-party flight planning application developer, I want to
programmatically query and retrieve all active NOTAMs relevant to a specific flight route
and time period, so that my application can automatically display critical aeronautical
information to pilots."

**Configuration:** AI's role: domain expert in aviation security · System: Aeronautical
Information System · Quality: INVEST · Formulation: user stories + acceptance criteria.

**Output shape (abridged):** *Assumptions & Scope* (UTC/ISO-8601, WGS-84, relevance =
spatial ∩ temporal ∩ active-after-supersession) → ~25 user stories covering querying, route
corridor construction, time/schedule validity, cancellation/replacement resolution, geometry
handling, altitude filtering, pagination, security (OAuth2), error handling (RFC 7807), rate
limiting, versioning, observability → *Risks / Points to Clarify* (corridor defaults,
criticality rules) → *Recommendation* (MVP subset).

**Why it is good:** assumptions first; functional and non-functional coverage; single
abstraction level; ends with risks and an MVP recommendation.

## 2. Banking — specify a vague requirement `[AI4RE-adapted]`

**Input:** "The online banking app must be secure when customers log in."

**Step 1–2:** No standard detected; input is a quality statement. Proposal: EARS for the
system behavior + one measurable NFR (ISO 29148 style). User confirms.

**Output:**
- "When a customer initiates a login, the online banking system shall require a second
  authentication factor compliant with PSD2 SCA before granting session access."
- "The online banking system shall lock an account for 30 minutes after 5 consecutive
  failed login attempts and notify the account holder via the registered channel."
- `Assumption:` PSD2 applies (EU market). `Open question:` are biometrics an approved
  second factor per the bank's security policy?

**Self-review:** "secure" (weak word) eliminated; actor, trigger, measure present; both
requirements testable; regulatory nuance → SME review recommended.

## 3. Medical device — synonym table `[AI4RE-adapted]`

**Input:** infusion pump specification using "alarm", "alert" and "notification"
interchangeably; "IFU", "instructions for use"; "occlusion" vs. "blockage".

**Output (excerpt):**

| Primary Term | Synonyms / Variants | Notes |
|---|---|---|
| Alarm | Alert | IEC 60601-1-8 distinguishes alarm priorities — "notification" is NOT a synonym (non-alarm information signal); flagged for harmonization |
| Instructions for Use | IFU | Commonly abbreviated as IFU |
| Occlusion | Blockage | "Occlusion" is the normative term; use consistently |

**Why it is good:** grounding rule respected; false equivalence (alarm/notification) caught
and flagged instead of merged — the safety-relevant distinction survives.

## 4. Agile / e-commerce — goal decomposition `[AI4RE-adapted]`

**Input goal:** "Increase checkout conversion."

**Output (SMART sub-goals, abridged):**
1. Reduce checkout abandonment rate from 68% to ≤ 55% by end of Q2 (`Assumption:` baseline
   68% from analytics — verify).
2. Cut median checkout duration from 4:10 min to ≤ 2:30 min within two releases.
3. Offer the three regionally dominant payment methods per target market by Q3.

Each sub-goal carries `Assumption:` markers for unverified baselines — the skill proposes
measures but does not invent sanctioned benchmarks.

## 5. Austrian public sector — NFRs incl. accessibility, no cross-references `[AI4RE-adapted]`

**Input (tender draft):** "ANF-31: Das Portal muss barrierefrei sein. ANF-32: Für die
Formulare gilt dasselbe wie in ANF-31, siehe auch Kapitel 4.2. ANF-33: Support auf Deutsch."

**Output (SOPHIST, MUSS/SOLL; category per ISO/IEC 25010:2023):**

| Category | Requirement |
|---|---|
| Interaktionsfähigkeit · Inklusivität | Das Portal MUSS die Konformitätsstufe AA der WCAG 2.1 sowie die anwendbaren Kriterien der EN 301 549 V3.2.1 erfüllen. |
| Interaktionsfähigkeit · Inklusivität | Das Portal MUSS die zum Download angebotenen Formulare barrierefrei gemäß EN 301 549 Klausel 10 bereitstellen. |
| Randbedingungen | Der Auftragnehmer MUSS bei Abgabe der Leistung einen Prüfbericht der Selbstüberprüfung nach WCAG 2.1 AA und EN 301 549 übergeben. |
| Randbedingungen | Der Auftragnehmer MUSS festgestellte Barrierefreiheitsmängel innerhalb der vereinbarten Frist ohne Zusatzkosten beheben. |
| Randbedingungen | Der Auftragnehmer MUSS den Support in deutscher Sprache erbringen. |

`Open question:` WCAG 2.1 or 2.2? (Beilage B: "jeweils aktuelle Fassung".)

**Self-review:** "dasselbe wie in ANF-31" and "siehe Kapitel 4.2" removed — content restated
so each requirement stands alone; vague "barrierefrei" anchored to WCAG/EN 301 549; product
vs. contractual obligations split into *Inklusivität* and *Randbedingungen*.
