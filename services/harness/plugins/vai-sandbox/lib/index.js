/**
 * vai-sandbox — DSH tools over the vAi Sandbox Kit broker (FastAPI).
 *
 * Tools registered (model-facing):
 *   sandbox_list / sandbox_create / sandbox_delete / sandbox_status
 *   sandbox_shell / sandbox_read_file / sandbox_write_file / sandbox_edit_file
 *   sandbox_list_dir / sandbox_find / sandbox_grep / sandbox_git / sandbox_git_clone
 *
 * Connection config resolution (per call — hot-reload):
 *   1. vault credentials (Settings → Secrets tab): VAI_SANDBOX_BROKER_URL, VAI_SANDBOX_TOKEN
 *   2. environment: same names
 *   3. plugin config (patch.yml): brokerUrl / token / defaultImage
 *
 * Broker API (verified live 117.5.151.111:9980):
 *   POST   /api/v1/management/sessions            {session_id?, project_path?, image?, cpu?, memory?, ttl?}
 *   GET    /api/v1/management/sessions
 *   DELETE /api/v1/management/sessions/{id}
 *   GET    /api/v1/agent/sessions/{id}/status
 *   POST   /api/v1/agent/execute                  {session_id, action:{...}}   (runShellCommand/runReadFile/...)
 *   POST   /api/v1/vfs/git/clone                  {workspace_id, url, branch?}
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, resolve, sep } from 'node:path'

export const name = 'vai-sandbox'
export const inject = ['tools', 'credentials']

const DEFAULT_BROKER = 'http://117.5.151.111:9980'
const CONN_TIMEOUT_MS = 15000
const SHELL_CEILING_MS = 10 * 60 * 1000

/** Per-call connection resolution (vault first, then env, then plugin config). */
function makeResolver(ctx, config) {
  return async (key, fallback) => {
    try {
      const resolved = await ctx.credentials.resolve(credentialRef(key))
      if (resolved && typeof resolved.value === 'string' && resolved.value !== '') return resolved.value
    } catch { /* credentials service without a store / unset key */ }
    return process.env[key] ?? config[key] ?? fallback
  }
}

class BrokerError extends Error { }

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const t = setTimeout(resolve, ms)
  if (signal) signal.addEventListener('abort', () => { clearTimeout(t); reject(new Error('sandbox request cancelled')) }, { once: true })
})

const isTransient = (err) => err instanceof BrokerError
  || /fetch failed|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ECONNREFUSED|network|socket|aborted this fetch/i.test(String((err && err.cause) || (err && err.message) || err))

/** One broker request with network/503 retry (public LB fronting the broker
 * intermittently resets connections and answers 503; direct internal URL
 * from the Secrets vault sidesteps it — retries cover the rest). */
async function brokerFetch({ url, token, method = 'GET', body, signal, timeoutMs = CONN_TIMEOUT_MS }) {
  const headers = { accept: 'application/json' }
  if (body !== undefined) headers['content-type'] = 'application/json'
  if (token) headers.authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`
  let lastErr
  for (let attempt = 0; attempt < 3; attempt++) {
    const deadline = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)])
    try {
      const res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: deadline })
      const text = await res.text()
      if (res.ok) {
        try { return JSON.parse(text) } catch { return text }
      }
      if (res.status >= 500 && attempt < 2) {
        lastErr = new BrokerError(`broker ${res.status} (upstream busy): ${text.slice(0, 120)}`)
        await sleep(500 * (attempt + 1), signal)
        continue
      }
      /* 4xx la ket qua nghiep vu cua broker (VD 404 'No active runner' — session
       * da chet): tra NGUYEN VAN thong bao cho agent, khong retry, khong doi ten
       * thanh 'unreachable'. */
      throw new BrokerError(`broker HTTP ${res.status}: ${text.slice(0, 400)}`)
    } catch (err) {
      if (signal && signal.aborted) throw new Error('sandbox request cancelled')
      if (!isTransient(err)) throw err
      lastErr = err
      if (attempt === 2) break
      await sleep(500 * (attempt + 1), signal)
    }
  }
  throw new BrokerError(`broker unreachable after 3 network attempts: ${url} (${(lastErr && (lastErr.cause || lastErr.message)) || lastErr})`)
}

/** POST /api/v1/agent/execute with one action envelope. */
async function executeAction({ base, token, sessionId, action, signal, timeoutMs }) {
  const data = await brokerFetch({
    url: `${base}/api/v1/agent/execute`,
    token, method: 'POST', signal, timeoutMs,
    body: { session_id: sessionId, action },
  })
  // {requestId, status, stdout, stderr, exitCode, error, response, source?}
  return data
}

const j = (value) => JSON.stringify(value)

/** Render stdout/stderr pairs the way terminal users read them. */
function renderExec(label) {
  return (_args, value) => {
    const v = typeof value === 'string' ? JSON.parse(value) : value
    const parts = []
    if (v.stdout) parts.push(v.stdout)
    if (v.stderr) parts.push(`[stderr]\n${v.stderr}`)
    parts.push(`[${label}] exit=${v.exitCode ?? 'n/a'}${v.error ? ` error=${v.error}` : ''}`)
    return [{ type: 'text', text: parts.join('\n') }]
  }
}

function str(desc, extra = {}) { return { type: 'string', description: desc, ...extra } }
function num(desc, extra = {}) { return { type: 'number', ...extra, description: desc } }
function bool(desc) { return { type: 'boolean', description: desc } }

/**
 * Register the sandbox toolset.
 * @param ctx - cordis host context (tools + credentials).
 * @param config - optional plugin config: {brokerUrl, token, defaultImage, defaultCpu, defaultMemory}.
 */
export function apply(ctx, config = {}) {
  const resolveCfg = makeResolver(ctx, config)

  const connection = async () => ({
    base: ((await resolveCfg('VAI_SANDBOX_BROKER_URL')) || config.brokerUrl || DEFAULT_BROKER).replace(/\/+$/, ''),
    token: (await resolveCfg('VAI_SANDBOX_TOKEN')) || config.token || '',
  })

  const T = defineTool
  const out = { schema: { type: 'string' } }

  ctx.tools.register(T({
    name: 'sandbox_list',
    description: 'List remote vAi-Sandbox Kit sessions (id, status, image, workspace, runner connected).',
    parameters: {},
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(_args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/management/sessions`, token, signal: exec.signal })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_create',
    description: 'Provision a remote sandbox container + runner. STANDARD WORKFLOW: (1) sandbox_git_clone {workspace_id: W, url} — clones into the server-side VFS, NO live sandbox needed; (2) sandbox_create {project_path: W} — project_path MUST equal that VFS workspace id, so every sandbox_shell auto-syncs those files into the container. Only use project_path=/workspace for throwaway sessions without VFS code. WORKFLOW to run a repo: (1) sandbox_git_clone it into a VFS workspace, (2) sandbox_create with project_path=/workspace (default), (3) wait ~5s then sandbox_status until runnerConnected=true, (4) sandbox_shell to build/run. Fields: image = docker image (default python:3.11-slim; also golang:1.22-alpine, node:22, ubuntu:latest); cpu = cores like 1 or 2; memory = like 1Gi or 4Gi; ttl = auto-delete seconds - set ttl greater than 0 (e.g. 3600) for auto cleanup; ttl=0 keeps until sandbox_delete.',
    parameters: {
      session_id: str('Optional explicit session id; broker generates one when omitted'),
      project_path: str('Workspace/project path inside the sandbox (default /workspace)'),
      image: str('Docker image for the sandbox (e.g. python:3.11-slim, ubuntu:latest)'),
      cpu: str('CPU limit (e.g. "2")'),
      memory: str('Memory limit (e.g. "4Gi")'),
      ttl: num('Auto-expiration seconds; 0 = keep until manual delete'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const body = {}
      if (args.session_id) body.session_id = args.session_id
      if (args.project_path) body.project_path = args.project_path
      body.image = args.image || config.defaultImage || 'python:3.11-slim'
      if (args.cpu) body.cpu = args.cpu
      if (args.memory) body.memory = args.memory
      body.ttl = args.ttl ?? 0
      const data = await brokerFetch({ url: `${base}/api/v1/management/sessions`, token, method: 'POST', body, signal: exec.signal, timeoutMs: 120000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_delete',
    description: 'Terminate and remove a remote vAi-Sandbox session.',
    parameters: { session_id: str('Session id to terminate') },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/management/sessions/${encodeURIComponent(args.session_id)}`, token, method: 'DELETE', signal: exec.signal, timeoutMs: 60000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_status',
    description: 'Get session status. Note: runnerConnected reflects the last reported state and can go stale — the authoritative check is just running sandbox_shell (a 404 No active runner means the session died: sandbox_create a fresh one).',
    parameters: { session_id: str('Session id') },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/agent/sessions/${encodeURIComponent(args.session_id)}/status`, token, signal: exec.signal })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_shell',
    description: 'Run a shell command in a remote sandbox. Files in the VFS workspace named by project_path are AUTO-SYNCED into the sandbox before every shell (VFS is the master copy). Errors: 404 No active runner = session dead/expired — call sandbox_create (new session_id) and retry the same command.',
    parameters: {
      session_id: str('Target sandbox session id'),
      command: str('Shell command to execute'),
      timeout: num('Command timeout seconds (default 120, max 600)'),
    },
    output: { ...out, render: renderExec('sandbox_shell') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const secs = Math.min(args.timeout ?? 120, 600)
      const data = await executeAction({
        base, token, sessionId: args.session_id, signal: exec.signal,
        timeoutMs: Math.min(secs * 1000 + 30000, SHELL_CEILING_MS + 30000),
        action: { runShellCommand: { command: args.command, timeout: secs } },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_read_file',
    description: 'Read a file from the vAi-Sandbox session workspace (project files resolve through VFS).',
    parameters: {
      session_id: str('Sandbox session id (or VFS workspace id)'),
      filepath: str('File path relative to workspace'),
      offset: num('Start line/offset (default 0)'),
      limit: num('Max lines to read'),
    },
    output: { ...out, render: renderExec('sandbox_read_file') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const act = { runReadFile: { filepath: args.filepath, offset: args.offset ?? 0, ...(args.limit ? { limit: args.limit } : {}) } }
      const data = await executeAction({ base, token, sessionId: args.session_id, action: act, signal: exec.signal, timeoutMs: 60000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_write_file',
    description: 'Create or overwrite a file (REQUIRES a LIVE runner session - it dies with the sandbox/ttl). For durable VFS edits prefer sandbox_vfs_write (no runner needed).',
    parameters: {
      session_id: str('Sandbox session id'),
      filepath: str('File path relative to workspace'),
      contents: str('Full file content to write'),
    },
    output: { ...out, render: renderExec('sandbox_write_file') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await executeAction({
        base, token, sessionId: args.session_id, signal: exec.signal, timeoutMs: 60000,
        action: { runWriteFile: { filepath: args.filepath, contents: args.contents } },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_edit_file',
    description: 'Find & replace a string inside a vAi-Sandbox workspace file.',
    parameters: {
      session_id: str('Sandbox session id'),
      filepath: str('File path relative to workspace'),
      oldString: str('Exact text to replace'),
      newString: str('Replacement text'),
    },
    output: { ...out, render: renderExec('sandbox_edit_file') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await executeAction({
        base, token, sessionId: args.session_id, signal: exec.signal, timeoutMs: 60000,
        action: { runEditFile: { filepath: args.filepath, oldString: args.oldString, newString: args.newString } },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_list_dir',
    description: 'List a directory inside the vAi-Sandbox workspace.',
    parameters: {
      session_id: str('Sandbox session id'),
      directory: str('Directory path relative to workspace (".") for root'),
    },
    output: { ...out, render: renderExec('sandbox_list_dir') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await executeAction({
        base, token, sessionId: args.session_id, signal: exec.signal, timeoutMs: 60000,
        action: { listDirectory: { directory: args.directory || '.' } },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_find',
    description: 'Find files by glob name pattern inside the vAi-Sandbox workspace.',
    parameters: {
      session_id: str('Sandbox session id'),
      name_pattern: str('Glob pattern, e.g. "*.py"'),
    },
    output: { ...out, render: renderExec('sandbox_find') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await executeAction({
        base, token, sessionId: args.session_id, signal: exec.signal, timeoutMs: 120000,
        action: { findFiles: { name_pattern: args.name_pattern } },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_grep',
    description: 'Search file contents inside the vAi-Sandbox workspace.',
    parameters: {
      session_id: str('Sandbox session id'),
      pattern: str('Search pattern'),
      search_directory: str('Directory to search (default workspace root)'),
      case_insensitive: bool('Case-insensitive match'),
    },
    output: { ...out, render: renderExec('sandbox_grep') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const g = { pattern: args.pattern }
      if (args.search_directory) g.search_directory = args.search_directory
      if (args.case_insensitive) g.case_insensitive = true
      const data = await executeAction({ base, token, sessionId: args.session_id, action: { grep: g }, signal: exec.signal, timeoutMs: 120000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_git',
    description: 'Run a git operation on a repository in the vAi-Sandbox (status, log, commit, ...).',
    parameters: {
      session_id: str('Sandbox session id'),
      command: str('Git subcommand, e.g. "status"'),
      arguments: str('Extra arguments string'),
      repository_url: str('Remote repository URL for fetch/clone style ops'),
    },
    output: { ...out, render: renderExec('sandbox_git') },
    async execute(args, exec) {
      const { base, token } = await connection()
      const g = { command: args.command, arguments: args.arguments ?? '' }
      if (args.repository_url) g.repository_url = args.repository_url
      const data = await executeAction({ base, token, sessionId: args.session_id, action: { runGitCommand: g }, signal: exec.signal, timeoutMs: 180000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_git_clone',
    description: 'Clone a git repository into a named VFS workspace on the vAi-Sandbox server (no live session needed). For private repos pass a PAT (or store VAI_GIT_TOKEN in Settings -> Secrets).',
    parameters: {
      workspace_id: str('Target VFS workspace id'),
      url: str('Repository URL (https/http)'),
      branch: str('Branch to clone (default main)'),
      token: str('Optional git PAT (GitHub/GitLab). Falls back to VAI_GIT_TOKEN secret, then VAI_SANDBOX_TOKEN'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const gitToken = args.token || await resolveCfg('VAI_GIT_TOKEN') || token || undefined
      const data = await brokerFetch({
        url: `${base}/api/v1/vfs/git/clone`, method: 'POST', signal: exec.signal, timeoutMs: 300000,
        body: { workspace_id: args.workspace_id, url: args.url, branch: args.branch || 'main', token: gitToken },
      })
      return j(data)
    },
  }))

  /* gitToken: explicit arg > VAI_GIT_TOKEN vault secret > broker token. */
  const gitTokenOf = async (args, brokerToken) => args.token || await resolveCfg('VAI_GIT_TOKEN') || brokerToken || undefined

  ctx.tools.register(T({
    name: 'sandbox_git_branch',
    description: 'Create (and by default check out) a branch in a VFS workspace. AGENT ROLE IS RESTRICTED TO BRANCHES STARTING WITH "agent-" (broker GitPolicy 403 otherwise). EDITOR now lives on that branch: subsequent write/edit tools modify it.',
    parameters: {
      workspace_id: str('VFS workspace id'),
      branch: str('Branch name (role agent: must start with "agent-")'),
      checkout: bool('Check out after creating (default true)'),
      role: str('Git role for broker policy: "agent" (default) or "human"'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({
        url: `${base}/api/v1/vfs/git/branch`, token: await gitTokenOf(args, token), method: 'POST', signal: exec.signal, timeoutMs: 60000,
        body: { workspace_id: args.workspace_id, branch: args.branch, checkout: args.checkout !== false, role: args.role || 'agent' },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_git_commit',
    description: 'Commit dirty VFS workspace files with a chosen identity (like a team member). Defaults author to vai-agent <agent@vaiplatform.local>; role agent is restricted to agent-* branches.',
    parameters: {
      workspace_id: str('VFS workspace id'),
      message: str('Commit message'),
      author_name: str('Author name (default "vai-agent")'),
      author_email: str('Author email (default agent@vaiplatform.local)'),
      role: str('Git role: "agent" (default) or "human"'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({
        url: `${base}/api/v1/vfs/git/commit`, token: await gitTokenOf(args, token), method: 'POST', signal: exec.signal, timeoutMs: 60000,
        body: {
          workspace_id: args.workspace_id, message: args.message,
          author_name: args.author_name || 'vai-agent', author_email: args.author_email || 'agent@vaiplatform.local',
          role: args.role || 'agent',
        },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_git_push',
    description: 'Push the workspace branch to its git remote, as one team member pushing their own branch. Private remotes need a PAT (explicit token arg, or the VAI_GIT_TOKEN secret). Agent role can only push agent-* branches.',
    parameters: {
      workspace_id: str('VFS workspace id'),
      remote_url: str('Override remote URL (uses the cloned remote when omitted)'),
      branch: str('Branch to push (defaults to the workspace current branch)'),
      token: str('Optional git PAT (fallback VAI_GIT_TOKEN secret)'),
      force: bool('Force push (default false)'),
      role: str('Git role: "agent" (default) or "human"'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const body = { workspace_id: args.workspace_id, force: args.force === true, role: args.role || 'agent' }
      body.token = await gitTokenOf(args, token)
      if (args.remote_url) body.remote_url = args.remote_url
      if (args.branch) body.branch = args.branch
      const data = await brokerFetch({
        url: `${base}/api/v1/vfs/git/push`, token: await gitTokenOf(args, token), method: 'POST', signal: exec.signal, timeoutMs: 180000,
        body,
      })
      return j(data)
    },
  }))

  /* VFS REST tools: broker -> vfs-service truc tiep, KHONG can runner song. */
  ctx.tools.register(T({
    name: 'sandbox_vfs_write',
    description: 'DURABLE write into a VFS workspace - NO live sandbox needed. Primary way to edit code: (1) sandbox_git_clone or existing workspace_id, (2) sandbox_git_branch agent-*, (3) sandbox_vfs_write files, (4) sandbox_git_commit + sandbox_git_push. Overwrites the whole file. TEXT: pass content. BINARY (images/pdf/zip): pass content_base64 (raw base64, no data: prefix) + is_binary true.',
    parameters: {
      workspace_id: str('VFS workspace id'),
      path: str('File path inside the workspace (e.g. src/main.py or shot.png)'),
      content: str('Full TEXT content to write (omit when writing binary)'),
      content_base64: str('Full BINARY content as raw base64 (no data:image/... prefix). Use for images from tools like steel screenshots'),
      is_binary: bool('Write as binary (with content_base64). Default false'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const isBinary = args.is_binary === true || (args.content_base64 !== undefined && args.content === undefined)
      const data = await brokerFetch({
        url: base + '/api/v1/vfs/file/write', token, method: 'POST', signal: exec.signal, timeoutMs: 120000,
        body: {
          workspace_id: args.workspace_id, path: args.path,
          content: isBinary ? (args.content_base64 ?? '') : args.content,
          is_binary: isBinary,
          encoding: isBinary ? 'base64' : 'utf-8',
        },
      })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_vfs_read',
    description: 'Read one file from a VFS workspace directly - NO live sandbox needed.',
    parameters: {
      workspace_id: str('VFS workspace id'),
      path: str('File path inside the workspace'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: typeof v === 'string' ? v.slice(0, 6000) : JSON.stringify(v).slice(0, 6000) }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const q = 'workspace_id=' + encodeURIComponent(args.workspace_id) + '&path=' + encodeURIComponent(args.path)
      const data = await brokerFetch({ url: base + '/api/v1/vfs/file/read?' + q, token, method: 'GET', signal: exec.signal, timeoutMs: 60000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_vfs_files',
    description: 'List files of a VFS workspace (path + size + sha256) - NO live sandbox needed.',
    parameters: { workspace_id: str('VFS workspace id') },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: base + '/api/v1/vfs/files?workspace_id=' + encodeURIComponent(args.workspace_id), token, method: 'GET', signal: exec.signal, timeoutMs: 60000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'sandbox_save_file',
    description: 'Save REAL BYTES (PNG screenshots, PDFs, any binary) or text DIRECTLY INTO THE DSH SESSION WORKSPACE - the same filesystem your read/write/present tools see. This is THE way to persist tool outputs like steel screenshots as real files. Sources (pick one): url = fetch raw bytes (e.g. a screenshot/PDF link returned by another tool), or content_base64, or text content. Path is workspace-relative (cwd-relative); parent dirs auto-created. Returns the absolute path - readable, presentable, and visible in the Web UI file tree.',
    parameters: {
      path: str('Workspace-relative file path (e.g. "shots/chinhphu.png")'),
      url: str('HTTP(S) URL to fetch raw bytes from (e.g. a screenshot artifact link). Cannot be a data: URL - pass those via content_base64 instead'),
      content_base64: str('Raw base64 bytes (strip any data:...;base64, prefix)'),
      content: str('Plain UTF-8 text (for text files)'),
    },
    output: { ...out, render: (_a, v) => [{ type: 'text', text: v }] },
    async execute(args, exec) {
      const sources = [args.url, args.content_base64, args.content].filter((x) => x !== undefined && x !== '')
      if (sources.length !== 1) throw new Error('pass exactly ONE of url / content_base64 / content')
      if (!args.path) throw new Error('path is required')
      const root = resolve(process.env.HOME || '/app/workspace')
      const target = resolve(root, args.path)
      if (target !== root && !target.startsWith(root + sep)) {
        throw new Error(`path escapes the workspace root: ${args.path}`)
      }
      let bytes
      if (args.url) {
        const res = await fetch(args.url, { signal: AbortSignal.any([exec.signal, AbortSignal.timeout(60000)]) })
        if (!res.ok) throw new Error(`fetch HTTP ${res.status}: ${args.url}`)
        bytes = Buffer.from(await res.arrayBuffer())
      } else if (args.content_base64 !== undefined && args.content_base64 !== '') {
        const b64 = args.content_base64.replace(/^data:[^;]*;base64,/, '')
        bytes = Buffer.from(b64, 'base64')
        if (bytes.length === 0) throw new Error('content_base64 decoded to 0 bytes - was the base64 truncated?')
      } else {
        bytes = Buffer.from(args.content ?? '', 'utf8')
      }
      await mkdir(dirname(target), { recursive: true })
      await writeFile(target, bytes)
      return j({ ok: true, path: target, bytes: bytes.length })
    },
  }))

  console.log('[vai-sandbox] 20 tools registered over Sandbox Kit broker (config via VAI_SANDBOX_BROKER_URL / VAI_SANDBOX_TOKEN)')
}
