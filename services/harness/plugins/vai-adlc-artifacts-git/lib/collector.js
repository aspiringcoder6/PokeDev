import { execFile } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile } from 'node:fs/promises'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { promisify } from 'node:util'

const runFile = promisify(execFile)
export const COLLECTOR_REF = 'plugin:vai-adlc-artifacts-git/0.2.0'
export const CAPTURE_PROFILE = 'harness-profile:adlc-coding-artifacts/0.1.0'
export const MAX_PATCH_BYTES = 512 * 1024
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const NULL_FILE = process.platform === 'win32' ? 'NUL' : '/dev/null'

export class GitArtifactError extends Error {
  constructor(code) {
    super(code)
    this.name = 'GitArtifactError'
    this.code = code
  }
}

function fail(code) { throw new GitArtifactError(code) }
function digest(value) { return createHash('sha256').update(value).digest('hex') }
function equal(left, right) { return JSON.stringify(left) === JSON.stringify(right) }
function childOf(root, path) {
  const part = relative(root, path)
  return part !== '' && part !== '..' && !part.startsWith(`..${sep}`) && !isAbsolute(part)
}

async function canonicalDirectory(path) {
  const suffix = []
  let parent = resolve(path)
  while (true) {
    try { return join(await realpath(parent), ...suffix) } catch (error) {
      if (error.code !== 'ENOENT' || dirname(parent) === parent) fail('HARNESS_ARTIFACT_CONFIG_INVALID')
      suffix.unshift(basename(parent))
      parent = dirname(parent)
    }
  }
}

function overlaps(left, right) { return relative(left, right) === '' || childOf(left, right) || childOf(right, left) }

function safeFile(file, allowedPaths) {
  const parts = file.split('/')
  if (!file || isAbsolute(file) || /[:\\\x00-\x1f\x7f]/u.test(file)
    || parts.some((part) => !part || part === '.' || part === '..')) fail('HARNESS_ARTIFACT_PATH_REJECTED')
  if (parts.some((part) => /^\.(git|ssh|aws|codex|agents|dsh)$/i.test(part)
    || /^\.env(?:\.|$)/i.test(part)
    || /^(?:credentials|secrets)(?:\.|$)/i.test(part)
    || /\.(?:pem|key|p12|pfx|ovpn)$/i.test(part))) fail('HARNESS_ARTIFACT_SENSITIVE_PATH')
  // Repository-wide capture never bypasses the path and sensitive-file guards above.
  // '*' is an explicit policy marker, not a filesystem glob or access outside cwd.
  if (!allowedPaths.some((path) => path === '*' || (path.endsWith('/') ? file.startsWith(path) : file === path))) {
    fail('HARNESS_ARTIFACT_PATH_NOT_ALLOWED')
  }
}

function gitEnvironment(globalConfig) {
  const env = {}
  for (const key of ['PATH', 'Path', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP']) {
    if (process.env[key] !== undefined) env[key] = process.env[key]
  }
  return { ...env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: globalConfig,
    GIT_TERMINAL_PROMPT: '0', GIT_OPTIONAL_LOCKS: '0', LC_ALL: 'C' }
}

async function git(cwd, args, { allowDiffExit = false, maxBuffer = MAX_PATCH_BYTES * 4,
  globalConfig = NULL_FILE, runner = runFile } = {}) {
  const options = { cwd, env: gitEnvironment(globalConfig), timeout: 30_000, maxBuffer, windowsHide: true, encoding: 'buffer' }
  const command = ['--no-replace-objects', '-c', `core.hooksPath=${NULL_FILE}`,
    '-c', 'core.autocrlf=false', '-c', 'core.quotePath=false', '-c', 'core.fsmonitor=false',
    '-c', `core.attributesFile=${NULL_FILE}`, '-c', `safe.directory=${cwd}`, '-c', 'protocol.ext.allow=never', ...args]
  let stdout
  try {
    stdout = (await runner('git', command, options)).stdout
  } catch (error) {
    if (allowDiffExit && error.code === 1) stdout = error.stdout
    else fail(error.code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' ? 'HARNESS_ARTIFACT_TOO_LARGE' : 'HARNESS_ARTIFACT_GIT_FAILED')
  }
  try { return new TextDecoder('utf-8', { fatal: true }).decode(stdout) } catch { fail('HARNESS_ARTIFACT_UNSUPPORTED_FILE') }
}

export class GitArtifactCollector {
  constructor({ dataDir, workspaceDir, profiles = {}, maxPatchBytes = MAX_PATCH_BYTES, maxFiles = 128,
    retentionMs = 24 * 60 * 60 * 1000, clock = Date.now, gitRunner = runFile } = {}) {
    this.dataDir = dataDir
    this.workspaceDir = workspaceDir
    this.profiles = structuredClone(profiles)
    this.maxPatchBytes = maxPatchBytes
    this.maxFiles = maxFiles
    this.retentionMs = retentionMs
    this.clock = clock
    this.gitRunner = gitRunner
    this.preparing = new Map()
    if (!dataDir || !workspaceDir || !isAbsolute(dataDir) || !isAbsolute(workspaceDir)
      || maxPatchBytes <= 0 || maxPatchBytes > MAX_PATCH_BYTES || maxFiles < 1 || maxFiles > 128
      || retentionMs <= 0 || retentionMs > 24 * 60 * 60 * 1000 || typeof gitRunner !== 'function') {
      fail('HARNESS_ARTIFACT_CONFIG_INVALID')
    }
  }

  supports(profileRef) { return Object.hasOwn(this.profiles, profileRef) }

  _git(cwd, args, options = {}) { return git(cwd, args, { ...options, runner: this.gitRunner }) }

  async _withSourceTransport(source, dataDir, operation) {
    const gitDir = await realpath((await this._git(source, ['rev-parse', '--absolute-git-dir'])).trim())
    await mkdir(dataDir, { recursive: true, mode: 0o700 })
    const temporary = await mkdtemp(join(dataDir, '.git-transport-'))
    const configPath = join(temporary, 'config')
    try {
      await writeFile(configPath, '', { flag: 'wx', mode: 0o600 })
      // Local upload-pack clears the parent's command-scoped config. A private file
      // reaches that child without trusting other repos or changing account config.
      // Let Git encode paths (including spaces/backslashes), never build shell text.
      for (const path of [source, gitDir]) {
        await this._git(dataDir, ['config', '--file', configPath, '--add', 'safe.directory', path])
      }
      return await operation({ globalConfig: configPath }, gitDir)
    } finally {
      // Only remove the freshly allocated private directory, never a repo/workspace.
      await rm(temporary, { recursive: true, force: true })
    }
  }

  async health() {
    const profiles = {}
    for (const [profileRef, profile] of Object.entries(this.profiles)) {
      try {
        if (!isAbsolute(profile.repository ?? '') || !Array.isArray(profile.allowedPaths) || profile.allowedPaths.length === 0) {
          fail('HARNESS_ARTIFACT_PROFILE_INVALID')
        }
        for (const path of profile.allowedPaths) safeFile(path.endsWith('/') ? `${path}placeholder` : path, [path])
        const { dataDir } = await this._layout(profile)
        const source = await realpath(profile.repository).catch(() => fail('HARNESS_ARTIFACT_SOURCE_UNAVAILABLE'))
        const top = (await this._git(source, ['rev-parse', '--show-toplevel'])).trim()
        if (await realpath(top) !== source) fail('HARNESS_ARTIFACT_SOURCE_NOT_ROOT')
        await this._git(source, ['rev-parse', '--verify', 'HEAD^{commit}'])
        // Read-only transport probe: HEAD alone misses ownership failures in clone.
        // No clone, model, network request or workspace is created by health checks.
        await this._withSourceTransport(source, dataDir, (options, gitDir) =>
          this._git(source, ['upload-pack', '--strict', '--advertise-refs', gitDir], options))
        profiles[profileRef] = { ready: true, error_code: null }
      } catch (error) {
        profiles[profileRef] = { ready: false, error_code: error instanceof GitArtifactError ? error.code : 'HARNESS_ARTIFACT_SOURCE_UNAVAILABLE' }
      }
    }
    return { ready: Object.keys(profiles).length > 0 && Object.values(profiles).every((profile) => profile.ready), profiles }
  }

  async prepare({ sessionId, request, resume = false }) {
    if (!UUID.test(sessionId) || Object.values(request.correlation).some((id) => !UUID.test(id))) {
      fail('HARNESS_ARTIFACT_CORRELATION_INVALID')
    }
    if (this.preparing.has(sessionId)) return this.preparing.get(sessionId)
    const operation = this._prepare({ sessionId, request, resume }).finally(() => this.preparing.delete(sessionId))
    this.preparing.set(sessionId, operation)
    return operation
  }

  async _prepare({ sessionId, request, resume }) {
    const profile = this.profiles[request.execution.profile_ref]
    if (!profile || !isAbsolute(profile.repository ?? '') || !Array.isArray(profile.allowedPaths)
      || profile.allowedPaths.length === 0) fail('HARNESS_ARTIFACT_PROFILE_INVALID')
    for (const path of profile.allowedPaths) safeFile(path.endsWith('/') ? `${path}placeholder` : path, [path])
    const { dataDir, root } = await this._layout(profile)
    await mkdir(dataDir, { recursive: true, mode: 0o700 })
    await mkdir(root, { recursive: true, mode: 0o700 })
    const cwd = join(root, sessionId)
    const manifestPath = join(dataDir, `${sessionId}.json`)
    let manifest
    try { manifest = JSON.parse(await readFile(manifestPath, 'utf8')) } catch (error) {
      if (error.code !== 'ENOENT') fail('HARNESS_ARTIFACT_MANIFEST_INVALID')
    }
    if (manifest !== undefined) {
      if (!equal(manifest.correlation, request.correlation) || manifest.profile_ref !== request.execution.profile_ref
        || manifest.cwd !== cwd || !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(manifest.base_commit)
        || !equal(manifest.allowed_paths, profile.allowedPaths)) fail('HARNESS_ARTIFACT_MANIFEST_CONFLICT')
      const actual = await realpath(cwd).catch(() => fail('HARNESS_ARTIFACT_WORKSPACE_MISSING'))
      if (actual !== cwd || !childOf(root, actual)) fail('HARNESS_ARTIFACT_PATH_REJECTED')
      await this._checkGitMetadata(cwd, manifest.git_config_digest)
      return { cwd, baseCommit: manifest.base_commit }
    }
    if (resume) fail('HARNESS_ARTIFACT_MANIFEST_MISSING')
    const source = await realpath(profile.repository).catch(() => fail('HARNESS_ARTIFACT_SOURCE_UNAVAILABLE'))
    if (source === root || childOf(source, root) || childOf(root, source)) fail('HARNESS_ARTIFACT_CONFIG_INVALID')
    const top = (await this._git(source, ['rev-parse', '--show-toplevel'])).trim()
    if (await realpath(top) !== source) fail('HARNESS_ARTIFACT_SOURCE_NOT_ROOT')
    const baseCommit = (await this._git(source, ['rev-parse', '--verify', 'HEAD^{commit}'])).trim()
    if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(baseCommit)) fail('HARNESS_ARTIFACT_GIT_FAILED')
    // A local clone copies committed content only, never the developer's dirty checkout,
    // credentials/config/hooks, or Git hardlinks. No remote is fetched or pushed.
    await this._withSourceTransport(source, dataDir, (options) =>
      this._git(root, ['clone', '--no-local', '--no-checkout', '--', source, cwd], options))
    await this._git(cwd, ['checkout', '--detach', baseCommit])
    await this._git(cwd, ['remote', 'remove', 'origin'])
    const tracked = (await this._git(cwd, ['ls-files', '--stage', '-z'])).split('\0').filter(Boolean)
    if (tracked.some((entry) => /^(120000|160000) /u.test(entry))) fail('HARNESS_ARTIFACT_UNSUPPORTED_FILE')
    manifest = { schema_version: '0.1', correlation: request.correlation, profile_ref: request.execution.profile_ref,
      cwd, base_commit: baseCommit, allowed_paths: profile.allowedPaths,
      git_config_digest: digest(await readFile(join(cwd, '.git', 'config'))) }
    await writeFile(manifestPath, JSON.stringify(manifest), { flag: 'wx', mode: 0o600 })
    return { cwd, baseCommit }
  }

  async _layout(profile) {
    const source = await canonicalDirectory(profile.repository)
    const dataDir = await canonicalDirectory(this.dataDir)
    const root = await canonicalDirectory(this.workspaceDir)
    if (overlaps(source, root) || overlaps(source, dataDir) || overlaps(dataDir, root)) fail('HARNESS_ARTIFACT_CONFIG_INVALID')
    return { dataDir, root }
  }

  async _checkGitMetadata(cwd, expectedConfig) {
    const gitDir = join(cwd, '.git')
    if (!(await lstat(gitDir)).isDirectory() || (await lstat(gitDir)).isSymbolicLink()
      || await realpath(gitDir) !== gitDir) fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED')
    for (const path of ['config', 'index', 'HEAD', 'objects', 'objects/pack', 'objects/info', 'refs']) {
      const stat = await lstat(join(gitDir, path)).catch(() => fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED'))
      if (stat.isSymbolicLink()) fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED')
      if (['config', 'index', 'HEAD'].includes(path) && !stat.isFile()) fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED')
    }
    if (digest(await readFile(join(gitDir, 'config'))) !== expectedConfig) fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED')
    for (const path of ['objects/info/alternates', 'objects/info/http-alternates']) {
      try { await lstat(join(gitDir, path)); fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED') } catch (error) {
        if (error.code !== 'ENOENT') throw error
      }
    }
    let entriesSeen = 0
    const checkTree = async (directory) => {
      for (const entry of await readdir(directory, { withFileTypes: true })) {
        entriesSeen += 1
        if (entriesSeen > 10_000 || entry.isSymbolicLink() || (!entry.isDirectory() && !entry.isFile())) {
          fail('HARNESS_ARTIFACT_GIT_METADATA_CHANGED')
        }
        if (entry.isDirectory()) await checkTree(join(directory, entry.name))
      }
    }
    await checkTree(join(gitDir, 'objects'))
    await checkTree(join(gitDir, 'refs'))
  }

  async collect({ sessionId, request }) {
    const captureStarted = Date.now()
    const { cwd, baseCommit } = await this.prepare({ sessionId, request, resume: true })
    const profile = this.profiles[request.execution.profile_ref]
    const changed = (await this._git(cwd, ['diff', '--no-renames', '--name-only', '-z', baseCommit, '--'])).split('\0').filter(Boolean)
    const untracked = (await this._git(cwd, ['ls-files', '--others', '--exclude-standard', '-z'])).split('\0').filter(Boolean)
    const names = [...new Set([...changed, ...untracked])].sort()
    if (names.length > this.maxFiles) fail('HARNESS_ARTIFACT_TOO_MANY_FILES')
    const files = []
    for (const file of names) {
      if (Date.now() - captureStarted > 60_000) fail('HARNESS_ARTIFACT_CAPTURE_TIMEOUT')
      safeFile(file, profile.allowedPaths)
      let exists = true
      try {
        const parts = file.split('/')
        for (let index = 1; index <= parts.length; index += 1) {
          const stat = await lstat(join(cwd, ...parts.slice(0, index)))
          if (stat.isSymbolicLink()) fail('HARNESS_ARTIFACT_UNSUPPORTED_FILE')
          if (index === parts.length && (!stat.isFile() || stat.size > this.maxPatchBytes)) fail('HARNESS_ARTIFACT_UNSUPPORTED_FILE')
        }
      } catch (error) {
        if (error.code !== 'ENOENT') throw error
        exists = false
      }
      const diff = untracked.includes(file)
        ? await this._git(cwd, ['diff', '--no-index', '--no-ext-diff', '--no-textconv', '--', NULL_FILE, file], { allowDiffExit: true })
        : await this._git(cwd, ['diff', '--no-renames', '--no-ext-diff', '--no-textconv', baseCommit, '--', file])
      if (/\x00|^Binary files |^GIT binary patch|^(?:old|new)(?: file)? mode (?:120000|160000)/mu.test(diff)) {
        fail('HARNESS_ARTIFACT_UNSUPPORTED_FILE')
      }
      if (!diff) continue
      let additions = 0
      let deletions = 0
      for (const line of diff.split('\n')) {
        if (line.startsWith('+') && !line.startsWith('+++')) additions += 1
        if (line.startsWith('-') && !line.startsWith('---')) deletions += 1
      }
      files.push({ file, patch: diff, additions, deletions,
        status: !exists ? 'DELETED' : untracked.includes(file) || diff.includes('new file mode') ? 'ADDED' : 'MODIFIED' })
      if (Buffer.byteLength(JSON.stringify(files)) > this.maxPatchBytes) fail('HARNESS_ARTIFACT_TOO_LARGE')
    }
    const snapshot = { format: 'harness-git-diff-v1', files, reported_files: names, base_commit: baseCommit }
    const payload = Buffer.from(JSON.stringify(snapshot), 'utf8')
    if (payload.length > this.maxPatchBytes) fail('HARNESS_ARTIFACT_TOO_LARGE')
    const artifactId = randomUUID()
    const createdAtMs = this.clock()
    const createdAt = new Date(createdAtMs).toISOString()
    const artifact = {
      schema_version: '0.1', artifact_id: artifactId,
      workflow_run_id: request.correlation.workflow_run_id, task_run_id: request.correlation.task_run_id,
      attempt_id: request.correlation.attempt_id, kind: 'SOURCE_PATCH', name: 'source-patch.json',
      media_type: 'application/json', uri: `adlc://runs/${request.correlation.workflow_run_id}/artifacts/${artifactId}`,
      size_bytes: payload.length, checksum: { algorithm: 'SHA256', value: digest(payload) },
      producer: COLLECTOR_REF, created_at: createdAt,
      expires_at: new Date(createdAtMs + this.retentionMs).toISOString(),
      metadata: { capture: 'harness-git-diff', format: snapshot.format, base_commit: baseCommit, file_count: files.length },
    }
    return { artifacts: [artifact], payloads: [{ artifact_id: artifactId, payload_base64: payload.toString('base64') }] }
  }
}
