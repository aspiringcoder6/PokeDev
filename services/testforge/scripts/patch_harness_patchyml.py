"""Patch patch.yml của agent-harness-server TRÊN SERVER (idempotent).

- Thêm block đăng ký plugin testforge-ai vào `- insert:` nếu chưa có.
- Thêm '/app/plugins/testforge-ai/skills' vào customSkillDirs nếu chưa có.

Chạy trên server: python3 /tmp/patch_harness_patchyml.py
"""
import pathlib
import re

PATCH = pathlib.Path("/opt/agent-harness-server/deepseek-harness/plugins/patch.yml")

PLUGIN_BLOCK = (
    "    # === TestForge AI (broker :9099) ===\n"
    "    - id: testforge-ai\n"
    "      name: '/app/plugins/testforge-ai/lib/index.js'\n"
    "      config:\n"
    "        url: 'http://10.0.10.195:9099'\n"
)

def main() -> None:
    s = PATCH.read_text(encoding="utf-8")
    changed = False
    if "id: testforge-ai" not in s:
        s = s.replace("    # === Sandbox Kit tools", PLUGIN_BLOCK + "    # === Sandbox Kit tools", 1)
        changed = True
        print("patch.yml: added plugin block")
    if "testforge-ai/skills" not in s:
        def _add(m: "re.Match[str]") -> str:
            inner = m.group(1).rstrip()
            sep = ", " if inner else ""
            return "customSkillDirs: [" + inner + sep + "'/app/plugins/testforge-ai/skills']"
        s, n = re.subn(r"customSkillDirs: \[([^\]]*)\]", _add, s, count=1)
        if n:
            changed = True
            print("patch.yml: added skills dir")
    if changed:
        PATCH.write_text(s, encoding="utf-8")
        print("patch.yml WRITTEN")
    else:
        print("patch.yml already up to date")


if __name__ == "__main__":
    main()
