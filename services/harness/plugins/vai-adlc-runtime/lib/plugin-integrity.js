import { createHash } from 'node:crypto'
import { readdir, readFile, realpath } from 'node:fs/promises'
import { isAbsolute, relative, resolve, sep } from 'node:path'

const PLUGIN_ID_PATTERN = /^[a-z0-9][a-z0-9._-]*$/
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/

async function filesBelow(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (entry.isSymbolicLink()) {
      throw new Error('Plugin bundles may not contain symbolic links.')
    }
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) {
      if (entry.name !== 'tests') files.push(...await filesBelow(path))
    } else if (entry.isFile()) {
      files.push(path)
    }
  }
  return files
}

function isBelow(root, candidate) {
  const projected = relative(root, candidate)
  return projected !== '' && projected !== '..' && !projected.startsWith(`..${sep}`) && !isAbsolute(projected)
}

function safeErrorCode(error) {
  if (error?.code === 'ENOENT') return 'MISSING'
  return 'UNREADABLE'
}

export async function digestInstalledPlugin(pluginRoot, pluginId) {
  if (typeof pluginId !== 'string' || !PLUGIN_ID_PATTERN.test(pluginId)) {
    throw new Error('Plugin id is invalid.')
  }
  const root = await realpath(resolve(pluginRoot))
  const directory = await realpath(resolve(root, pluginId))
  if (!isBelow(root, directory)) throw new Error('Plugin directory escapes the configured plugin root.')

  const manifest = JSON.parse(await readFile(resolve(directory, 'package.json'), 'utf8'))
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new Error('Plugin package manifest must be an object.')
  }
  if (manifest.name !== pluginId || typeof manifest.version !== 'string' || manifest.version.trim() === '') {
    throw new Error('Plugin package identity does not match its directory.')
  }

  const hash = createHash('sha256')
  const files = (await filesBelow(directory))
    .map((path) => ({ path, relativePath: relative(directory, path).split(sep).join('/') }))
    .sort((left, right) => left.relativePath < right.relativePath ? -1 : left.relativePath > right.relativePath ? 1 : 0)
  for (const file of files) {
    hash.update(file.relativePath)
    hash.update(Buffer.from([0]))
    hash.update(await readFile(file.path))
    hash.update(Buffer.from([0]))
  }
  return {
    plugin_id: pluginId,
    version: manifest.version,
    content_digest: `sha256:${hash.digest('hex')}`,
  }
}

export async function verifyInstalledPluginLock(pluginRoot, expectedLock, clock = Date.now) {
  const entries = []
  let configurationValid = Array.isArray(expectedLock) && expectedLock.length > 0
  const seen = new Set()

  for (const expected of Array.isArray(expectedLock) ? expectedLock : []) {
    const pluginId = expected?.plugin_id
    const expectedValid = typeof pluginId === 'string'
      && PLUGIN_ID_PATTERN.test(pluginId)
      && !seen.has(pluginId)
      && typeof expected.version === 'string'
      && expected.version.trim() !== ''
      && DIGEST_PATTERN.test(expected.content_digest ?? '')
      && typeof expected.required === 'boolean'
    if (!expectedValid) {
      configurationValid = false
      entries.push({
        plugin_id: typeof pluginId === 'string' ? pluginId : 'invalid-plugin-id',
        required: expected?.required === true,
        expected_version: typeof expected?.version === 'string' ? expected.version : '',
        expected_digest: typeof expected?.content_digest === 'string' ? expected.content_digest : '',
        installed_version: null,
        installed_digest: null,
        status: 'LOCK_INVALID',
      })
      continue
    }
    seen.add(pluginId)
    try {
      const installed = await digestInstalledPlugin(pluginRoot, pluginId)
      const status = installed.version !== expected.version
        ? 'VERSION_MISMATCH'
        : installed.content_digest !== expected.content_digest
          ? 'DIGEST_MISMATCH'
          : 'EXACT'
      entries.push({
        plugin_id: pluginId,
        required: expected.required,
        expected_version: expected.version,
        expected_digest: expected.content_digest,
        installed_version: installed.version,
        installed_digest: installed.content_digest,
        status,
      })
    } catch (error) {
      entries.push({
        plugin_id: pluginId,
        required: expected.required,
        expected_version: expected.version,
        expected_digest: expected.content_digest,
        installed_version: null,
        installed_digest: null,
        status: safeErrorCode(error),
      })
    }
  }

  const ready = configurationValid && entries.every((entry) => !entry.required || entry.status === 'EXACT')
  return {
    schema_version: '0.1',
    ready,
    checked_at: new Date(clock()).toISOString(),
    error_code: ready ? null : configurationValid ? 'HARNESS_PLUGIN_INTEGRITY_FAILED' : 'HARNESS_PLUGIN_LOCK_INVALID',
    plugins: entries,
  }
}

