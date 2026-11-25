import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync, lstatSync, realpathSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { SessionMemoryClient } from './session-memory.js'
import { TnqdPreviews } from './tnqd-previews.js'

export const TNQD_ROOT = '/api/v1/pokedev-services/tnqd'
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/
const scopePattern = /^[a-f0-9]{64}$/
const slug = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/
const sha = value => createHash('sha256').update(value).digest('hex')
const fail = code => { throw new Error(code) }
const text = value => (value?.content ?? []).map(c => c.text ?? '').join('\n')

export class TnqdBridge {
  constructor(checks, directory) { this.checks = checks; this.root = directory; this.jobs = new Map();this.previews=new TnqdPreviews(checks,join(directory,'previews')) }
  folder(id, scope) {
    if (!uuid.test(id) || !scopePattern.test(scope)) fail('TNQD_SCOPE_INVALID')
    return join(this.root, scope, id)
  }
  prepare(c) {
    const directory = this.folder(c.run_id, c.scope_id)
    if (!Array.isArray(c.nodes) || !c.nodes.length || c.nodes.length > 32) fail('TNQD_NODE_LIMIT')
    const seen = new Set()
    for (const node of c.nodes) {
      if (!slug.test(node.id) || seen.has(node.id)) fail('TNQD_NODE_INVALID')
      seen.add(node.id)
      if (!node.inputs || Object.entries(node.inputs).some(([p, value]) => !/^[\w.-]{1,80}$/.test(p)
        || typeof value !== 'string' || Buffer.byteLength(value) > 180000)) fail('TNQD_INPUT_INVALID')
    }
    const receiptFile = join(directory, 'receipt.json')
    let previous = { run_id: c.run_id, scope_id: c.scope_id, nodes: [], created_at: new Date().toISOString() }
    try {
      const old = JSON.parse(readFileSync(receiptFile, 'utf8'))
      if (old.run_id !== c.run_id || old.scope_id !== c.scope_id) fail('TNQD_ID_CONFLICT')
      previous = old
    } catch (error) { if (error.code !== 'ENOENT') throw error }
    mkdirSync(directory, { recursive: true })
    const nodes = c.nodes.map(node => {
      const incoming = Object.fromEntries(Object.entries(node.inputs).map(([p, value]) => [p, sha(value)]))
      const existing = previous.nodes.find(n => n.id === node.id)
      if (existing) {
        if (JSON.stringify(existing.inputs) !== JSON.stringify(incoming)) fail('TNQD_NODE_INPUT_CONFLICT')
        return existing
      }
      const workspace = join(directory, node.id)
      mkdirSync(join(workspace, 'inputs'), { recursive: true })
      mkdirSync(join(workspace, 'outputs'), { recursive: true })
      const hashes = {}
      for (const [p, value] of Object.entries(node.inputs)) {
        writeFileSync(join(workspace, 'inputs', p), value, { mode: 0o600 })
        hashes[p] = sha(value)
      }
      return { id: node.id, workspace, inputs: hashes }
    })
    const combined = [...previous.nodes.filter(n => !seen.has(n.id)), ...nodes]
    if (combined.length > 32) fail('TNQD_NODE_LIMIT')
    const receipt = { ...previous, binding: sha(JSON.stringify(combined)), nodes: combined }
    writeFileSync(receiptFile + '.tmp', JSON.stringify(receipt), { mode: 0o600 }); renameSync(receiptFile + '.tmp', receiptFile)
    return receipt
  }
  read(id, scope, node) {
    const directory = this.folder(id, scope)
    const receipt = JSON.parse(readFileSync(join(directory, 'receipt.json'), 'utf8'))
    if (!node) return receipt
    const bound = receipt.nodes.find(n => n.id === node)
    if (!bound) fail('TNQD_NODE_UNKNOWN')
    const path = join(bound.workspace, 'outputs', 'result.json')
    const stat = lstatSync(path)
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 180000
      || !realpathSync(path).startsWith(resolve(bound.workspace) + sep)) fail('TNQD_ARTIFACT_INVALID')
    const raw = readFileSync(path, 'utf8')
    const inputs_intact = Object.entries(bound.inputs).every(([p, digest]) => sha(readFileSync(join(bound.workspace, 'inputs', p))) === digest)
    if (!inputs_intact) fail('TNQD_INPUT_CHANGED')
    return { node_id: node, run_id: id, inputs_intact, sha256: sha(raw), artifact: JSON.parse(raw) }
  }
  async memory(c) {
    if (!scopePattern.test(c.scope_id) || !slug.test(c.document_id) || !slug.test(c.revision)
      || !['publish', 'read'].includes(c.operation)) fail('TNQD_MEMORY_COMMAND_INVALID')
    const directory = join(this.root, c.scope_id, 'documents')
    mkdirSync(directory, { recursive: true })
    const file = join(directory, c.document_id + '--' + c.revision + '.json')
    let record
    if (c.operation === 'publish') {
      if (typeof c.body !== 'string' || !c.body.trim() || Buffer.byteLength(c.body) > 100000) fail('TNQD_DOCUMENT_TOO_LARGE')
      record = { document_id: c.document_id, revision: c.revision, body: c.body, sha256: sha(c.body),
        source_ref: String(c.source_ref ?? '').slice(0, 500), state: 'PUBLISHING', chunks: [] }
      try {
        const old = JSON.parse(readFileSync(file, 'utf8'))
        if (old.sha256 !== record.sha256) fail('TNQD_DOCUMENT_REVISION_CONFLICT')
        if (old.state === 'PUBLISHED') record = old
        else fail('TNQD_DOCUMENT_PUBLICATION_UNCONFIRMED')
      } catch (error) { if (error.code !== 'ENOENT') throw error }
    } else record = JSON.parse(readFileSync(file, 'utf8'))
    const controller = new AbortController()
    const health = this.checks.tool ? await (async()=>{let r=await this.checks.tool('memory_health').execute({}, {signal:controller.signal});return typeof r==='string'?JSON.parse(r):r})() : await this.checks.call({steps:[],controller},'memory_health',{})
    const client = new SessionMemoryClient(health.url, controller.signal)
    await client.initialize()
    if (c.operation === 'publish' && record.state !== 'PUBLISHED') {
      writeFileSync(file, JSON.stringify(record), { flag: 'wx', mode: 0o600 })
      for (let start = 0, index = 0; start < record.body.length; start += 1800, index++) {
        const part = record.body.slice(start, start + 1800)
        const chunk = { index, digest: sha(part), session_id: 'tnqd-' + sha(c.scope_id + c.document_id + c.revision + index).slice(0, 48) }
        const payload = Buffer.from(JSON.stringify({ document_id: c.document_id, revision: c.revision, index, body: part, digest: chunk.digest })).toString('base64')
        const answer = await client.call('remember', { session_id: chunk.session_id, data: 'TNQDDOCJSON:' + payload, self_improvement: false })
        if (!text(answer).includes('session_stored')) fail('TNQD_MEMORY_WRITE_UNCONFIRMED')
        record.chunks.push(chunk)
      }
      record.state = 'PUBLISHED'
      record.published_at = new Date().toISOString()
      writeFileSync(file + '.tmp', JSON.stringify(record), { mode: 0o600 }); renameSync(file + '.tmp', file)
    }
    if (record.state !== 'PUBLISHED') fail('TNQD_MEMORY_NOT_PUBLISHED')
    let recalled = ''
    for (const chunk of record.chunks) {
      const answer = await client.call('recall', { session_id: chunk.session_id, query: 'TNQDDOCJSON', top_k: 1 })
      const matches = [...text(answer).matchAll(/TNQDDOCJSON:([A-Za-z0-9+/=]+)/g)]
      const parsed = matches.map(m => { try { return JSON.parse(Buffer.from(m[1], 'base64').toString()) } catch { return null } })
        .find(p => p?.document_id === c.document_id && p.revision === c.revision && p.index === chunk.index && sha(p.body) === chunk.digest)
      if (!parsed) fail('TNQD_MEMORY_CONTENT_MISMATCH')
      recalled += parsed.body
    }
    if (sha(recalled) !== record.sha256) fail('TNQD_MEMORY_DOCUMENT_MISMATCH')
    return { document_id: record.document_id, revision: record.revision, body: recalled, sha256: record.sha256,
      source_ref: record.source_ref, mode: 'COGNEE_PROJECT_SESSION_CHUNKS', chunk_count: record.chunks.length,
      retrieved_at: new Date().toISOString(), graph_ingestion: false, durable_graph_verified: false,
      content_verified: true, caller_context_id: c.caller_context_id ?? null }
  }
}

export function tnqdHandler(bridge, authenticate) {
  return async (request, response) => {
    const send = (status, value) => { response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' }); response.end(JSON.stringify(value)) }
    try {
      const rejection = authenticate?.(request) ?? (authenticate ? undefined : 503)
      if (rejection !== undefined) return send(rejection, { error_code: 'TNQD_UNAUTHENTICATED' })
      const url = new URL(request.url, 'http://platform.local')
      const match = new RegExp('^' + TNQD_ROOT + '/runs/([a-f0-9-]{36})$').exec(url.pathname)
      const preview = new RegExp('^'+TNQD_ROOT+'/previews/([a-f0-9-]{36})(/(?:test|http|chunks|commit))?$').exec(url.pathname)
      if (request.method === 'GET' && match) return send(200, bridge.read(match[1], url.searchParams.get('scope_id'), url.searchParams.get('node_id')))
      if (request.method === 'GET' && preview && !preview[2]) return send(200,bridge.previews.read(preview[1],url.searchParams.get('scope_id')))
      if (request.method === 'POST' && ([TNQD_ROOT + '/runs', TNQD_ROOT + '/memory',TNQD_ROOT+'/previews',TNQD_ROOT+'/previews/upload'].includes(url.pathname) || preview?.[2])) {
        const chunks = []; let size = 0
        const limit=url.pathname===TNQD_ROOT+'/previews'?81000000:1500000
        for await (const chunk of request) { size += chunk.length; if (size > limit) fail('TNQD_REQUEST_TOO_LARGE'); chunks.push(Buffer.from(chunk)) }
        const command = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        if(url.pathname===TNQD_ROOT+'/previews/upload')return send(200,bridge.previews.upload(command))
        if(preview?.[2]==='/chunks')return send(200,bridge.previews.chunk(preview[1],command))
        if(preview?.[2]==='/commit')return send(202,bridge.previews.commit(preview[1],command))
        if(preview?.[2]==='/http')return send(200,await bridge.previews.http(preview[1],command))
        if(preview?.[2]==='/test')return send(202,bridge.previews.test(preview[1],command))
        if(url.pathname===TNQD_ROOT+'/previews')return send(202,bridge.previews.begin(command))
        return send(200, url.pathname.endsWith('/memory') ? await bridge.memory(command) : bridge.prepare(command))
      }
      return send(404, { error_code: 'TNQD_NOT_FOUND' })
    } catch (error) { return send(error.code === 'ENOENT' ? 404 : 409, { error_code: /^TNQD_[A-Z_]+$/.test(error.message) ? error.message : 'TNQD_OPERATION_FAILED' }) }
  }
}
