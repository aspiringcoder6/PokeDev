# vai-testforce (id: testforge-ai) — plugin DSH, bản portable

> **NGUỒN CHUẨN CỦA agent-harness-server là trên server** (`/opt/agent-harness-server`
> qua SSH). Thư mục này chỉ là bản portable để scp lên server — bản clone
> `D:\VTS\agent-harness-server` ở máy local ĐÃ CŨ, không được push từ đó.

## Files (scp thẳng vào server)
```
plugin/testforge-ai/lib/index.js            → /opt/agent-harness-server/deepseek-harness/plugins/testforge-ai/lib/index.js
plugin/testforge-ai/package.json            → .../testforge-ai/package.json
plugin/testforge-ai/skills/testforge-ai/SKILL.md → .../testforge-ai/skills/testforge-ai/SKILL.md
```

## patch.yml (trên server) — đăng ký trong block `- insert:`
```yaml
    # === TestForge AI (broker :9099) ===
    - id: testforge-ai
      name: '/app/plugins/testforge-ai/lib/index.js'
      config:
        url: 'http://10.0.10.195:9099'
```
Và `skill-filesystem` customSkillDirs thêm `'/app/plugins/testforge-ai/skills'`.

## Secrets vault (UI Settings → Secrets)
- `TESTFORGE_BROKER_URL` = `http://10.0.10.195:9099`
- `TESTFORGE_BROKER_TOKEN` = token broker (trùng `opt/broker.env`)

## 8 tools
health · explore · replay · staging · perf · fetch-testcase · recommend · result
