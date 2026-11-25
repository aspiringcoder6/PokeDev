/**
 * vai-taskloop — HTTP API Routes
 *
 * Session-scoped (web form / SSE):
 * - GET  /api/taskloop/events?session=...   -> SSE stream
 * - GET  /api/taskloop/current?session=...  -> Current task contract JSON & rendered prompt
 * - POST /api/taskloop/save?session=...     -> Save updated task contract from web form
 * - POST /api/taskloop/status?session=...   -> Change contract status (viewer quick buttons)
 * - GET  /api/taskloop/viewer/*             -> Interactive TaskLoop Form web app
 *
 * File-scoped (SDK / external orchestrator control plane):
 * - POST /api/taskloop/contract?session=...  body {dir, contract, brief?} -> CREATE (no overwrite)
 * - GET  /api/taskloop/task?dir=&n=                                       -> READ one contract
 * - GET  /api/taskloop/tasks?dir=                                         -> LIST all contracts
 * - PATCH /api/taskloop/contract?session=... body {dir, n, patch, comment?} -> UPDATE (merge)
 *
 * File-scoped rules: create-only (existing files are never overwritten or
 * deleted), every written path stays inside the caller-supplied `dir`
 * (contract briefs must be relative paths), `dir` must be absolute.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { TASK_STATUSES } from './goal-bridge.js'
import { TaskLoopEngine } from './engine.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const VIEWER_DIR = path.resolve(__dirname, '../viewer')
const PREFIX = '/api/taskloop'

const MIME_MAP = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
}

function serveStatic(req, res, subPath) {
  let rel = subPath.startsWith('/viewer/') ? subPath.slice('/viewer/'.length) : ''
  if (!rel || rel === '/' || rel === 'index.html') rel = 'index.html'

  const safePath = path.resolve(VIEWER_DIR, rel)
  if (!safePath.startsWith(VIEWER_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain' })
    res.end('Forbidden')
    return
  }

  let filePath = safePath
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    filePath = path.join(VIEWER_DIR, 'index.html')
  }

  if (!fs.existsSync(filePath)) {
    res.writeHead(404, { 'Content-Type': 'text/plain' })
    res.end('Viewer index.html not found.')
    return
  }

  const ext = path.extname(filePath).toLowerCase()
  const contentType = MIME_MAP[ext] || 'application/octet-stream'

  try {
    const data = fs.readFileSync(filePath)
    res.writeHead(200, {
      'Content-Type': contentType,
      'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable',
      'Access-Control-Allow-Origin': '*'
    })
    res.end(data)
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'text/plain' })
    res.end(`File read error: ${err.message}`)
  }
}

const TASK_FILE_PATTERN = /^task-\d+\.task\.json$/

/** Resolve + guard the caller-supplied workspace directory. */
function resolveWorkspaceDir(dirParam) {
  if (typeof dirParam !== 'string' || !dirParam.trim()) return null
  if (!path.isAbsolute(dirParam)) return null
  return path.resolve(dirParam)
}

function contractFilePath(dir, n) {
  return path.join(dir, 'taskloop', `task-${String(n || '1')}.task.json`)
}

/** Whether `target` stays inside `dir` (path-traversal guard for briefs). */
function isInside(dir, target) {
  const rel = path.relative(dir, target)
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel)
}

function writeJsonFile(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8')
}

/** Restore an engine from stored JSON without stamping a fresh updatedAt. */
function engineFromStored(stored) {
  const engine = new TaskLoopEngine(stored)
  if (stored && typeof stored.updatedAt === 'string') engine.updatedAt = stored.updatedAt
  return engine
}

function syncSessionEngine(sessionMap, eventBus, session, engine, event) {
  if (!session) return
  sessionMap.set(session, engine)
  eventBus.broadcast(session, event, engine.toJSON())
}

function readJson(req, res, onBody) {
  let body = ''
  req.on('data', chunk => { body += chunk })
  req.on('end', () => {
    try {
      onBody(JSON.parse(body || '{}'))
    } catch (err) {
      badRequest(res, err.message)
    }
  })
}

function badRequest(res, message) {
  res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify({ ok: false, error: message }))
}

export function registerRoutes(ctx, sessionMap, eventBus) {
  const webServer = ctx.get('webServer')
  if (!webServer) {
    ctx.logger?.warn?.('vai-taskloop: webServer not available, HTTP endpoints skipped')
    return () => {}
  }

  return webServer.register({
    kind: 'prefix',
    path: PREFIX,
    handler: async (req, res) => {
      // Custom webServer prefixes do not inherit the RPC transport auth fence.
      const rejection = typeof ctx.connection?.requestRejection === 'function'
        ? ctx.connection.requestRejection(req) : 503
      if (rejection !== undefined) {
        res.writeHead(rejection, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify({ ok: false, error: rejection === 401 ? 'Unauthenticated' : 'Access denied' }))
        return
      }
      const url = new URL(req.url || '/', 'http://127.0.0.1')
      const pathname = url.pathname
      const sub = pathname.startsWith(PREFIX) ? pathname.slice(PREFIX.length) : pathname
      const session = url.searchParams.get('session') || 'default'
      const fileParam = url.searchParams.get('file')

      try {
        // Static Viewer Files
        if (sub === '/viewer' || sub.startsWith('/viewer/')) {
          serveStatic(req, res, sub)
          return
        }

        // SSE Event Stream
        if (sub === '/events' && req.method === 'GET') {
          eventBus.connect(res, session)
          return
        }

        // Get Current Task Contract JSON
        if (sub === '/current' && req.method === 'GET') {
          // If a file is specified, try reading from disk first
          if (fileParam) {
            try {
              const fullPath = path.isAbsolute(fileParam) ? fileParam : path.resolve(process.cwd(), fileParam)
              if (fs.existsSync(fullPath)) {
                const content = JSON.parse(fs.readFileSync(fullPath, 'utf8'))
                const engine = new TaskLoopEngine(content)
                sessionMap.set(session, engine)
                res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
                res.end(JSON.stringify(engine.toJSON()))
                return
              }
            } catch (e) {
              console.warn('[vai-taskloop] reading fileParam error:', e)
            }
          }

          let engine = sessionMap.get(session)
          if (!engine) {
            // Default placeholder task
            engine = new TaskLoopEngine({
              n: '1',
              name: '',
              model: 'sonnet',
              brief: '',
              dir: '',
              report: '',
              ctx: ''
            })
            sessionMap.set(session, engine)
          }

          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
          res.end(JSON.stringify(engine.toJSON()))
          return
        }

        // Save Task Contract (POST from Form)
        if (sub === '/save' && (req.method === 'POST' || req.method === 'PUT')) {
          let body = ''
          req.on('data', chunk => { body += chunk })
          req.on('end', () => {
            try {
              const parsed = JSON.parse(body || '{}')
              let engine = sessionMap.get(session)
              if (!engine) {
                engine = new TaskLoopEngine(parsed)
                sessionMap.set(session, engine)
              } else {
                engine.update(parsed)
              }

              const json = engine.toJSON()

              // Auto save to file if requested or default; prefer the
              // canonical per-session taskloop dir remembered by the tools.
              const fileName = `task-${engine.n || 1}.task.json`
              const targetFile = fileParam || parsed.filePath || (engine.storeDir ? path.join(engine.storeDir, fileName) : fileName)
              try {
                const writePath = path.isAbsolute(targetFile) ? targetFile : path.resolve(process.cwd(), targetFile)
                fs.mkdirSync(path.dirname(writePath), { recursive: true })
                fs.writeFileSync(writePath, JSON.stringify(json, null, 2), 'utf8')
              } catch (writeErr) {
                console.warn('[vai-taskloop] save file error:', writeErr)
              }

              // Broadcast via SSE to all connected clients
              eventBus.broadcast(session, 'task_updated', json)

              res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
              res.end(JSON.stringify({ ok: true, data: json }))
            } catch (err) {
              res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
              res.end(JSON.stringify({ ok: false, error: err.message }))
            }
          })
          return
        }

        // Change task status (viewer quick buttons)
        if (sub === '/status' && (req.method === 'POST' || req.method === 'PUT')) {
          let body = ''
          req.on('data', chunk => { body += chunk })
          req.on('end', () => {
            try {
              const parsed = JSON.parse(body || '{}')
              const status = String(parsed.status || '').trim()
              if (!TASK_STATUSES.includes(status)) {
                res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(JSON.stringify({ ok: false, error: `Invalid status "${status}". Allowed: ${TASK_STATUSES.join(' | ')}` }))
                return
              }
              let engine = sessionMap.get(session)
              if (!engine) {
                engine = new TaskLoopEngine({ n: '1', model: 'sonnet', status })
                sessionMap.set(session, engine)
              } else {
                engine.update({ status })
              }
              const json = engine.toJSON()

              // Persist to the canonical store so the file-as-truth tools
              // pick the change up on their next read.
              const fileName = `task-${engine.n || 1}.task.json`
              const targetFile = fileParam || (engine.storeDir ? path.join(engine.storeDir, fileName) : fileName)
              try {
                const writePath = path.isAbsolute(targetFile) ? targetFile : path.resolve(process.cwd(), targetFile)
                fs.mkdirSync(path.dirname(writePath), { recursive: true })
                fs.writeFileSync(writePath, JSON.stringify(json, null, 2), 'utf8')
              } catch (writeErr) {
                console.warn('[vai-taskloop] status file error:', writeErr)
              }

              eventBus.broadcast(session, 'task_updated', json)
              res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
              res.end(JSON.stringify({ ok: true, data: json }))
            } catch (err) {
              res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' })
              res.end(JSON.stringify({ ok: false, error: err.message }))
            }
          })
          return
        }

        // ── File-scoped contract store (SDK / external orchestrator) ──

        // Create one task contract on disk (never overwrites an existing one).
        if (sub === '/contract' && req.method === 'POST') {
          readJson(req, res, (body) => {
            const dir = resolveWorkspaceDir(body.dir)
            if (!dir) return badRequest(res, 'dir must be an absolute workspace path')
            const contract = body.contract
            if (!contract || typeof contract !== 'object') return badRequest(res, 'contract object is required')
            if (contract.status && !TASK_STATUSES.includes(contract.status)) {
              return badRequest(res, `Invalid status "${contract.status}". Allowed: ${TASK_STATUSES.join(' | ')}`)
            }
            const n = String(contract.n || '1')
            const filePath = contractFilePath(dir, n)
            if (fs.existsSync(filePath)) {
              res.writeHead(409, { 'Content-Type': 'application/json; charset=utf-8' })
              res.end(JSON.stringify({ ok: false, error: `task-${n}.task.json already exists in ${path.join(dir, 'taskloop')} — use PATCH to modify` }))
              return
            }
            const briefPath = contract.brief ? path.resolve(dir, contract.brief) : null
            if (briefPath && !isInside(dir, briefPath)) {
              return badRequest(res, 'brief must be a relative path inside dir')
            }
            const engine = new TaskLoopEngine({ ...contract, n })
            const json = engine.toJSON()
            engine.storeDir = path.dirname(filePath)
            writeJsonFile(filePath, json)
            if (briefPath && typeof body.brief === 'string') {
              fs.mkdirSync(path.dirname(briefPath), { recursive: true })
              fs.writeFileSync(briefPath, String(body.brief), 'utf8')
            }
            syncSessionEngine(sessionMap, eventBus, url.searchParams.get('session'), engine, 'task_created')
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
            res.end(JSON.stringify({ ok: true, file: filePath, contract: json, prompt: json.prompt }))
          })
          return
        }

        // Merge a patch (fields / status / comment) into an existing contract.
        if (sub === '/contract' && req.method === 'PATCH') {
          readJson(req, res, (body) => {
            const dir = resolveWorkspaceDir(body.dir)
            if (!dir) return badRequest(res, 'dir must be an absolute workspace path')
            const n = String(body.n || '1')
            const filePath = contractFilePath(dir, n)
            if (!fs.existsSync(filePath)) {
              res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' })
              res.end(JSON.stringify({ ok: false, error: `task-${n}.task.json not found in ${path.join(dir, 'taskloop')}` }))
              return
            }
            const patch = body.patch && typeof body.patch === 'object' ? body.patch : {}
            if (patch.status && !TASK_STATUSES.includes(patch.status)) {
              return badRequest(res, `Invalid status "${patch.status}". Allowed: ${TASK_STATUSES.join(' | ')}`)
            }
            if (patch.n !== undefined && String(patch.n) !== n) {
              return badRequest(res, 'patch.n cannot rename the task file')
            }
            const stored = JSON.parse(fs.readFileSync(filePath, 'utf8'))
            const engine = engineFromStored(stored)
            engine.storeDir = path.dirname(filePath)
            const { comment: patchComment, ...fields } = patch
            engine.update(fields)
            const comment = body.comment && typeof body.comment === 'object' ? body.comment : patchComment
            if (comment && typeof comment === 'object') engine.addComment(comment.author, comment.text)
            const json = engine.toJSON()
            writeJsonFile(filePath, json)
            syncSessionEngine(sessionMap, eventBus, url.searchParams.get('session'), engine, 'task_updated')
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
            res.end(JSON.stringify({ ok: true, file: filePath, contract: json }))
          })
          return
        }

        // Read one stored contract file.
        if (sub === '/task' && req.method === 'GET') {
          const dir = resolveWorkspaceDir(url.searchParams.get('dir'))
          if (!dir) return badRequest(res, 'dir must be an absolute workspace path')
          const n = url.searchParams.get('n') || '1'
          const filePath = contractFilePath(dir, n)
          if (!fs.existsSync(filePath)) {
            res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8' })
            res.end(JSON.stringify({ ok: false, error: `task-${n}.task.json not found in ${path.join(dir, 'taskloop')}` }))
            return
          }
          const stored = JSON.parse(fs.readFileSync(filePath, 'utf8'))
          const engine = engineFromStored(stored)
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
          res.end(JSON.stringify({ ok: true, file: filePath, contract: engine.toJSON() }))
          return
        }

        // List every stored contract in a workspace.
        if (sub === '/tasks' && req.method === 'GET') {
          const dir = resolveWorkspaceDir(url.searchParams.get('dir'))
          if (!dir) return badRequest(res, 'dir must be an absolute workspace path')
          const loopDir = path.join(dir, 'taskloop')
          const files = fs.existsSync(loopDir) && fs.statSync(loopDir).isDirectory()
            ? fs.readdirSync(loopDir).filter(f => TASK_FILE_PATTERN.test(f)).sort()
            : []
          const tasks = files.map((f) => {
            try {
              return engineFromStored(JSON.parse(fs.readFileSync(path.join(loopDir, f), 'utf8'))).toJSON()
            } catch {
              return null
            }
          }).filter(Boolean)
          res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*' })
          res.end(JSON.stringify({ ok: true, dir, count: tasks.length, tasks }))
          return
        }

        res.writeHead(404, { 'Content-Type': 'text/plain' })
        res.end('Not found')
      } catch (err) {
        res.writeHead(500, { 'Content-Type': 'text/plain' })
        res.end(`Internal error: ${err.message}`)
      }
    }
  })
}
