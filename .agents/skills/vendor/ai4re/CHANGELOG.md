# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Changed

- `requirements-writing` 1.1.0: requirements must be self-contained — cross-references to
  other requirements, IDs or chapters are forbidden (quality gate, self-review, checklist,
  system prompt).
- `requirements-writing`: NFRs classified by ISO/IEC 25010:2023 (9 categories) plus
  *Randbedingungen*; decomposition walks all ten categories.
- `requirements-translation` 1.1.0: NFRs in reverse-engineered specifications grouped by
  ISO/IEC 25010:2023 + *Randbedingungen* (category table in `references/templates.md`).
- `requirements-traceability` 1.1.0: ISO/IEC 25010:2023 + *Randbedingungen* as default NFR
  taxonomy for *Tag Requirements* (Q01–Q10 with include criteria).

### Added

- `requirements-writing/references/nfr-quality-model.md`: ISO/IEC 25010:2023 model and
  accessibility knowledge for Austrian public-sector catalogues (WZG, WCAG AA,
  EN 301 549 clauses, BMSGPK Vertragsbeilage B obligations, acceptance test tools).
- Example 5: Austrian tender NFRs incl. accessibility, cross-references removed.

## [1.0.0] — 2026-07-06

### Added

- Initial release: complete transfer of the IREB AI4RE Prompt Guide (23 use cases,
  9 clusters, 4 IREB core activities) into 9 specialized Claude Skills:
  `elicitation-preparation`, `elicitation-transcription`, `requirements-extraction`,
  `requirements-writing`, `requirements-translation`, `requirements-validation`,
  `requirements-verification`, `change-impact-analysis`, `requirements-traceability`.
- Supervisor skill `ai4re-master`: request classification, routing table for all 23 use
  cases, 6 standard multi-skill workflows (W1–W6), shared-context management, cross-skill
  quality review.
- Per skill: `SKILL.md` plus references (AI4RE templates verbatim-preserved, checklists,
  prompt patterns, multi-domain examples, standalone system prompt for non-Claude tools).
- Documentation: architecture, AI4RE knowledge base (taxonomy, pattern catalog, pitfall
  taxonomy), skill overview, installation, examples, skill authoring guide.
- End-to-end domain scenarios: software-project, automotive, medical-device,
  agile-banking.
- Claude Code plugin + marketplace configuration (`.claude-plugin/`).
- Skill scaffold in `templates/skill-template/` and contribution guidelines.
- Provenance system: `[AI4RE]` / `[AI4RE-adapted]` / `[Supplementary: <source>]` tags
  throughout; attribution in `NOTICE.md`.
