# Contributing

Thank you for helping turn the IREB AI4RE Prompt Guide into ever-better Claude Skills.

## Ground rules

1. **Provenance is non-negotiable.** Every section you add carries a source tag:
   `[AI4RE]`, `[AI4RE-adapted]` or `[Supplementary: <source>]` — rules in
   [NOTICE.md](NOTICE.md) and [docs/skill-authoring-guide.md](docs/skill-authoring-guide.md) §5.
   Never present supplementary content as guide content.
2. **AI4RE template wording is preserved.** When the guide's templates change upstream,
   update `references/templates.md` verbatim (formatting fixes only) and adjust the
   skill's workflow around it.
3. **Follow the authoring guide.** [docs/skill-authoring-guide.md](docs/skill-authoring-guide.md)
   defines the mandatory structure; [skills/requirements-writing/](skills/requirements-writing/SKILL.md)
   is the reference implementation.

## Adding a new skill

1. Copy [templates/skill-template/](templates/skill-template/) to `skills/<your-skill-name>/`.
2. Fill in all six files; work through the checklist in the authoring guide §7.
3. Register the skill in:
   - `docs/skill-overview.md` (table row)
   - `skills/ai4re-master/references/routing.md` (routing + preconditions)
   - `README.md` (skills table)
4. Add a `CHANGELOG.md` entry under *Unreleased*.
5. Open a pull request describing which AI4RE use case(s) — or which gap (see knowledge
   base §8) — the skill covers.

## Changing an existing skill

- Keep `SKILL.md` under 500 lines; push bulk to `references/`.
- Behavioral rules (ask-before-assume, grounding, self-review, draft labeling, …) may be
  strengthened, never removed.
- Bump the skill's `version` (SemVer: fix = patch, new capability = minor, breaking
  restructure = major) and mirror it in `CHANGELOG.md`.

## Versioning & releases

The plugin version in `.claude-plugin/plugin.json` follows the repository release; skill
versions evolve independently. Releases are tagged `v<major>.<minor>.<patch>`.

## Quality bar for PRs

- English, active voice, imperative instructions; no marketing language.
- No content duplication between SKILL.md and references.
- Examples cover ≥ 3 distinct domains per skill.
- Markdown lints clean (consistent headings, tables well-formed).

## Reporting issues

Use GitHub issues. For upstream guide changes (new use cases, changed templates), link the
guide page and label the issue `ai4re-sync`.
