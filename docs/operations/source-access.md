# Application-owned source access

Set `ADLC_SOURCE_BINDINGS_FILE` to a backend-owned JSON file containing `connections` and `projects`.
Keep credentials in a secret store or backend environment. Connection rows contain secret reference names only.

```json
{"connections":[{"connection_id":"gh","provider":"github","app_id":"123","installation_id":"456","private_key_secret_ref":"GITHUB_APP_KEY"}],"projects":{"demo":{"principals":["normalizer"],"resources":{"gh":["org/repo"]},"max_reads":24,"max_bytes":500000}}}
```

Install a GitHub App on selected repositories with Contents, Issues and Pull requests read permissions.
For Lark use an approved tenant app (`app_id`, `tenant_id`, `app_secret_ref`), add its bot to permitted chats,
grant Base collaborator access, and separately share linked documents. Wiki node permission does not grant
permission to its target. Base table restrictions use `locator_allowlists: {"lark:base1":{"table_id":["tbl1"]}}`.
Field restrictions fail closed until projection and schema/cell redaction are implemented.

Build the gateway once with `build_source_gateway(settings, secret_resolver)` and close it with `await gateway.aclose()`.
Reload operator settings and call `resolve_project_grant` before every batch; never reuse an old grant after revocation.
The workflow retains cumulative budgets. Tokens refresh automatically; rotate app secrets behind stable reference names.
Never accept grants, tokens, arbitrary origins or secret values from an agent or normalizer.

Offline acceptance uses HTTP fixtures. Live acceptance remains pending operator provisioning: read a pinned GitHub
file and Issue/comments, a paginated Lark thread, and a Base record plus separately granted linked document.
Record source IDs, versions and denial outcomes without credentials. Verify cross-project denial before HTTP I/O.
