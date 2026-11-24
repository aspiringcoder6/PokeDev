# User preferences

- Build and verify PokeDev interfaces for desktop. Do not add mobile layouts or mobile-specific work unless the user explicitly requests it. This preference applies to future work in this repository.

# Network context

- OpenVPN currently supports normal access. An intermittent VPN routing fault has previously left internal Harness/Gitea reachable while external services such as Slack, Google and Confluence timed out. If this recurs, check connectivity and routing before treating credentials or integrations as broken. Prefer the existing Workloop/MCP integration for server-side Confluence access when direct access is unavailable. Preserve VPN settings; do not apply routing workarounds unless the user explicitly requests them.

# PokeDev fork direction

- Build on the vAIPlatform control plane. Do not introduce new Workloop dependencies; retain existing ones only while replacing the documented legacy paths.
- Use GitHub for source hosting and the target repository adapter. Existing Gitea code is migration context.
- Keep the PokeDev product name and restored PokeDev assets. Keep backend API namespaces stable unless a migration requires a versioned change.
- Configure credentials and runtime data independently from ADLC. Do not copy its databases, sessions, tokens or local recovery settings.
