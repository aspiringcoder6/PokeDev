# Installation

## Option 1 — Claude Code plugin (recommended)

```
/plugin marketplace add chrsbrmr/ai4re-skill
/plugin install ai4re
```

All 10 skills become available immediately; Claude activates them automatically when a
request matches a skill description. Verify with `/plugin` → installed plugins → `ai4re`.

## Option 2 — Manual skill installation

Copy the skill directories to your skills folder:

- **Personal (all projects):** `~/.claude/skills/`
- **Project (shared via git):** `<project>/.claude/skills/`

```bash
git clone https://github.com/chrsbrmr/ai4re-skill.git
cp -r ai4re-skill/skills/* ~/.claude/skills/
```

You can install a subset — each skill is self-contained. Keep `ai4re-master` if you want
multi-skill orchestration; its routing table lists all sibling skills, missing ones are
simply skipped.

## Option 3 — claude.ai / Claude API

Upload individual skill folders as custom skills (claude.ai Pro/Max/Team with skills
enabled), or use them with the Agent SDK by pointing `skills` at the `skills/` directory.

## Option 4 — Any other LLM tool

Every skill ships `references/system-prompt.md` — a standalone system prompt encoding the
skill's discipline. Copy it into the system prompt of your tool and replace the
`[VARIABLES]`.

## Requirements

- Claude Code ≥ 2.x for plugin installation (Agent Skills support).
- No build steps, no dependencies — the repository is pure markdown + JSON.

## Updating

```
/plugin marketplace update ai4re
```

or `git pull` + re-copy for manual installations. Version history: [CHANGELOG.md](../CHANGELOG.md).
