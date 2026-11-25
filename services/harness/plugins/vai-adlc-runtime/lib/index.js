import { timingSafeEqual } from 'node:crypto'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { credentialRef } from '@deepseek-ai/dsh-credentials'

import { HarnessRuntime, HarnessRuntimeError } from './runtime.js'
import { verifyInstalledPluginLock } from './plugin-integrity.js'

export const name = 'vai-adlc-runtime'
export const inject = ['webServer', 'credentials', 'adlcVerifier', 'adlcExecutionDriver', 'adlcArtifactCollector']

const API_ROOT = '/api/v1/adlc-harness'
const BODY_LIMIT_BYTES = 1024 * 1024

function sendJson(response, status, value) {
  response.writeHead(status, {
    'cache-control': 'no-store',
    'content-type': 'application/json; charset=utf-8',
  })
  response.end(JSON.stringify(value))
}

async function readJsonBody(request) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
    size += buffer.length
    if (size > BODY_LIMIT_BYTES) {
      throw new HarnessRuntimeError('HARNESS_REQUEST_TOO_LARGE', 'The request body is too large.', 413)
    }
    chunks.push(buffer)
  }
  if (chunks.length === 0) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  } catch {
    throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID_JSON', 'The request body is not valid JSON.', 400)
  }
}

function secureEqual(left, right) {
  const leftBuffer = Buffer.from(left)
  const rightBuffer = Buffer.from(right)
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer)
}

export function apply(ctx, config = {}) {
  const resolveSetting = async (key, fallback = '') => {
    try {
      const resolved = await ctx.credentials.resolve(credentialRef(key))
      if (resolved && typeof resolved.value === 'string' && resolved.value !== '') return resolved.value
    } catch {
      // An unset vault key intentionally falls through to deployment configuration.
    }
    return process.env[key] ?? fallback
  }

  const callbackRef = config.callbackRef ?? 'adlc-primary'
  const runtime = new HarnessRuntime({
    dataDir: config.dataDir ?? join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), 'adlc-harness'),
    callbackConfig: async () => ({
      ref: callbackRef,
      url: await resolveSetting('ADLC_HARNESS_CALLBACK_URL', config.callbackUrl ?? ''),
      secret: await resolveSetting('ADLC_HARNESS_CALLBACK_SECRET', config.callbackSecret ?? ''),
    }),
    verifier: ctx.adlcVerifier,
    driver: ctx.adlcExecutionDriver,
    artifactCollector: ctx.adlcArtifactCollector,
    requiredPluginLock: config.pluginLock ?? [],
    pluginIntegrityVerifier: (pluginLock) => verifyInstalledPluginLock(
      config.pluginRoot ?? '/app/plugins',
      pluginLock,
    ),
  })

  const requireBearer = async (request, response) => {
    const expected = await resolveSetting('ADLC_HARNESS_API_TOKEN', config.apiToken ?? '')
    if (expected === '') {
      sendJson(response, 503, { error: { code: 'HARNESS_API_NOT_CONFIGURED', message: 'Harness API authentication is not configured.' } })
      return false
    }
    const authorization = request.headers.authorization ?? ''
    const supplied = authorization.startsWith('Bearer ') ? authorization.slice(7) : ''
    if (!secureEqual(supplied, expected)) {
      sendJson(response, 401, { error: { code: 'HARNESS_API_UNAUTHENTICATED', message: 'A valid bearer token is required.' } })
      return false
    }
    return true
  }

  const handle = async (request, response) => {
    if (!(await requireBearer(request, response))) return
    try {
      const url = new URL(request.url ?? '/', 'http://harness.local')
      if (url.pathname === `${API_ROOT}/health` && request.method === 'GET') {
        sendJson(response, 200, await runtime.health())
        return
      }
      if (url.pathname === `${API_ROOT}/plugins` && request.method === 'GET') {
        sendJson(response, 200, await runtime.getPluginInventory({ refresh: true }))
        return
      }
      if (url.pathname === `${API_ROOT}/sessions` && request.method === 'POST') {
        sendJson(response, 202, await runtime.createSession(await readJsonBody(request)))
        return
      }

      const interactionMatch = new RegExp(`^${API_ROOT}/sessions/([^/]+)/interactions/([^/]+)/responses$`).exec(url.pathname)
      if (interactionMatch !== null && request.method === 'POST') {
        const sessionId = decodeURIComponent(interactionMatch[1])
        const interactionId = decodeURIComponent(interactionMatch[2])
        sendJson(response, 202, await runtime.respondToInteraction(
          sessionId,
          interactionId,
          await readJsonBody(request),
        ))
        return
      }

      const artifactMatch = new RegExp(`^${API_ROOT}/sessions/([^/]+)/artifacts/([^/]+)$`).exec(url.pathname)
      if (artifactMatch !== null && request.method === 'GET') {
        sendJson(response, 200, await runtime.getArtifact(
          decodeURIComponent(artifactMatch[1]), decodeURIComponent(artifactMatch[2]),
        ))
        return
      }

      const match = new RegExp(`^${API_ROOT}/sessions/([^/]+)(?:/(submit|cancel))?$`).exec(url.pathname)
      if (match !== null) {
        const sessionId = decodeURIComponent(match[1])
        const action = match[2]
        if (action === undefined && request.method === 'GET') {
          sendJson(response, 200, await runtime.getSession(sessionId))
          return
        }
        if (action === 'submit' && request.method === 'POST') {
          await readJsonBody(request)
          sendJson(response, 202, await runtime.submitSession(sessionId))
          return
        }
        if (action === 'cancel' && request.method === 'POST') {
          await readJsonBody(request)
          sendJson(response, 200, await runtime.cancelSession(sessionId))
          return
        }
      }
      sendJson(response, 404, { error: { code: 'HARNESS_ROUTE_NOT_FOUND', message: 'The Harness API route was not found.' } })
    } catch (error) {
      if (error instanceof HarnessRuntimeError) {
        sendJson(response, error.status, { error: { code: error.code, message: error.message } })
        return
      }
      console.error('[vai-adlc-runtime] request failed', error)
      sendJson(response, 500, { error: { code: 'HARNESS_INTERNAL_ERROR', message: 'The Harness request failed.' } })
    }
  }

  ctx.webServer.register({ kind: 'prefix', path: API_ROOT, handler: handle })
  ctx.effect?.(() => () => void runtime.close())
  console.log(`[vai-adlc-runtime] ADLC Harness API ready at ${API_ROOT}`)
}
