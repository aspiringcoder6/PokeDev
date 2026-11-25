import { createHash,randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { join, extname } from 'node:path'
import { inflateRawSync } from 'node:zlib'

const uuid = /^[a-f0-9-]{36}$/
const scope = /^[a-f0-9]{64}$/
const sha = s => createHash('sha256').update(s).digest('hex')
const fail = code => { throw Error(code) }
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const MIME = {'.html':'text/html; charset=utf-8','.js':'application/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.ico':'image/x-icon','.woff':'font/woff','.woff2':'font/woff2','.ttf':'font/ttf'}

// Only archives produced by the bounded runner, no executable caller commands.
export function unpackArtifact(buffer) {
  const files = new Map(); let offset = 0, expanded = 0
  while (offset+30 <= buffer.length && buffer.readUInt32LE(offset) === 0x04034b50) {
    const flags=buffer.readUInt16LE(offset+6), method=buffer.readUInt16LE(offset+8), size=buffer.readUInt32LE(offset+18), length=buffer.readUInt32LE(offset+22), nameSize=buffer.readUInt16LE(offset+26), extra=buffer.readUInt16LE(offset+28)
    const name=buffer.subarray(offset+30,offset+30+nameSize).toString('utf8'), start=offset+30+nameSize+extra
    if (flags & 9 || ![0,8].includes(method) || name.startsWith('/') || name.includes('\\') || name.split('/').some(s=>s==='..' || s==='.') || start+size>buffer.length || length>16000000 || files.has('/'+name)) fail('TNQD_ARCHIVE_INVALID')
    const data=method===8?inflateRawSync(buffer.subarray(start,start+size),{maxOutputLength:16000000}):buffer.subarray(start,start+size)
    expanded+=data.length
    if (data.length!==length || expanded>120000000 || files.size>12000) fail('TNQD_ARCHIVE_LIMIT')
    if (!name.endsWith('/')) files.set('/'+name,data)
    offset=start+size
  }
  if (!files.has('/index.html')) fail('TNQD_ARCHIVE_INDEX_REQUIRED')
  return files
}

export class TnqdPreviews {
  constructor(checks, root) { this.checks=checks;this.root=root;this.jobs=new Map();this.assets=new Map() }
  persist(job) {mkdirSync(this.root,{recursive:true});const p=join(this.root,job.preview_id+'.json');writeFileSync(p+'.tmp',JSON.stringify(job),{mode:0o600});renameSync(p+'.tmp',p)}
  upload(c) {
    if(!uuid.test(c.preview_id??'')||!scope.test(c.scope_id??'')||!/^[a-f0-9]{64}$/.test(c.artifact_sha256??'')||!Number.isInteger(c.chunks)||c.chunks<1||c.chunks>1000||!Number.isInteger(c.bytes)||c.bytes<1||c.bytes>60000000)fail('TNQD_UPLOAD_INVALID')
    c={preview_id:c.preview_id,scope_id:c.scope_id,artifact_sha256:c.artifact_sha256,chunks:c.chunks,bytes:c.bytes}
    mkdirSync(this.root,{recursive:true});const file=join(this.root,'upload-'+c.preview_id+'.json')
    try{const old=JSON.parse(readFileSync(file,'utf8'));if(JSON.stringify(old)!==JSON.stringify(c))fail('TNQD_UPLOAD_CONFLICT');return {state:'UPLOADING',preview_id:c.preview_id}}catch(e){if(e.code!=='ENOENT')throw e}
    writeFileSync(file,JSON.stringify(c),{flag:'wx',mode:0o600});return {state:'UPLOADING',preview_id:c.preview_id}
  }
  uploadRecord(id,s) {
    if(!uuid.test(id??'')||!scope.test(s??''))fail('TNQD_UPLOAD_NOT_FOUND')
    let record;try{record=JSON.parse(readFileSync(join(this.root,'upload-'+id+'.json'),'utf8'))}catch{fail('TNQD_UPLOAD_NOT_FOUND')}
    if(record.scope_id!==s)fail('TNQD_UPLOAD_NOT_FOUND');return record
  }
  chunk(id,c) {
    const record=this.uploadRecord(id,c.scope_id)
    if(!Number.isInteger(c.index)||c.index<0||c.index>=record.chunks||typeof c.data!=='string'||!c.data.length||c.data.length>240000||!/^[A-Za-z0-9+/=]+$/.test(c.data))fail('TNQD_UPLOAD_CHUNK_INVALID')
    const file=join(this.root,'upload-'+id+'-'+String(c.index).padStart(5,'0')+'.txt')
    try{if(readFileSync(file,'utf8')!==c.data)fail('TNQD_UPLOAD_CHUNK_CONFLICT')}catch(e){if(e.code!=='ENOENT')throw e;writeFileSync(file,c.data,{flag:'wx',mode:0o600})}
    return {received:c.index,preview_id:id}
  }
  commit(id,c) {
    const record=this.uploadRecord(id,c.scope_id)
    let encoded=''
    for(let i=0;i<record.chunks;i++){try{encoded+=readFileSync(join(this.root,'upload-'+id+'-'+String(i).padStart(5,'0')+'.txt'),'utf8')}catch{fail('TNQD_UPLOAD_INCOMPLETE')}}
    const archive=Buffer.from(encoded,'base64')
    if(archive.length!==record.bytes||sha(archive)!==record.artifact_sha256)fail('TNQD_UPLOAD_HASH_MISMATCH')
    return this.begin({preview_id:id,scope_id:c.scope_id,artifact_sha256:record.artifact_sha256,archive_base64:encoded})
  }
  read(id,s) {
    if (!uuid.test(id??'') || !scope.test(s??'')) fail('TNQD_PREVIEW_NOT_FOUND')
    let job=this.jobs.get(id)
    if (!job) {
      try {job=JSON.parse(readFileSync(join(this.root,id+'.json'),'utf8'))}catch{fail('TNQD_PREVIEW_NOT_FOUND')}
      if (job.state==='DEPLOYING') {job.state='UNCONFIRMED';job.error_code='TNQD_PREVIEW_INTERRUPTED'}
      if (job.testforge?.state==='RUNNING') {job.testforge.state='UNCONFIRMED'}
    }
    if(job.scope_id!==s) fail('TNQD_PREVIEW_NOT_FOUND')
    if(Date.parse(job.expires_at)<=Date.now()) job={...job,state:'EXPIRED'}
    return structuredClone(job)
  }
  async call(job,name,args) {
    const tool=this.checks.tool(name)
    if(!tool?.execute) fail('TNQD_SERVICE_TOOL_UNAVAILABLE')
    let result=await tool.execute(args,{signal:AbortSignal.timeout(240000),callId:randomUUID()})
    if(typeof result==='string') {try{result=JSON.parse(result)}catch{fail('TNQD_SERVICE_RESPONSE_INVALID')}}
    return result
  }
  begin(c) {
    if(!uuid.test(c.preview_id??'') || !scope.test(c.scope_id??'') || !/^[a-f0-9]{64}$/.test(c.artifact_sha256??'') || typeof c.archive_base64!=='string' || c.archive_base64.length>80000000) fail('TNQD_PREVIEW_COMMAND_INVALID')
    try {const old=this.read(c.preview_id,c.scope_id);if(old.artifact_sha256!==c.artifact_sha256)fail('TNQD_PREVIEW_ID_CONFLICT');return old}catch(e){if(e.message!=='TNQD_PREVIEW_NOT_FOUND')throw e}
    try{readFileSync(join(this.root,c.preview_id+'.json'));fail('TNQD_PREVIEW_ID_CONFLICT')}catch(e){if(e.code!=='ENOENT')throw e}
    const archive=Buffer.from(c.archive_base64,'base64')
    if(sha(archive)!==c.artifact_sha256)fail('TNQD_PREVIEW_HASH_INVALID')
    const assets=unpackArtifact(archive)
    if([...this.jobs.values()].some(j=>j.state==='DEPLOYING'))fail('TNQD_PREVIEW_CAPACITY')
    mkdirSync(this.root,{recursive:true});writeFileSync(join(this.root,c.preview_id+'.zip'),archive,{mode:0o600})
    const job={preview_id:c.preview_id,scope_id:c.scope_id,artifact_sha256:c.artifact_sha256,state:'DEPLOYING',created_at:new Date().toISOString(),expires_at:new Date(Date.now()+7200000).toISOString(),sandbox_id:'pokedev-tnqd-'+c.preview_id,image:'adlc-test-worker:local',data_mode:'API fixture · quyền chỉ đọc',access_mode:'POKEDEV_TNQD_RELAY',static_mode:'HASH_VERIFIED_DEPLOYED_ARTIFACT_CACHE',port:8088,verification_evidence:false}
    this.assets.set(c.preview_id,assets);this.jobs.set(c.preview_id,job);this.persist(job)
    void this.deploy(job,c.archive_base64).catch(()=>{})
    return this.read(c.preview_id,c.scope_id)
  }
  async deploy(job,content) {
    try {
      const health=await this.call(job,'testforge_health',{})
      if(health.sandbox_image!==job.image)fail('TNQD_TESTFORGE_IMAGE_MISMATCH')
      const created=await this.call(job,'sandbox_create',{session_id:job.sandbox_id,project_path:job.sandbox_id,image:job.image,cpu:'1',memory:'2Gi',ttl:7200})
      if((created.sessionId??created.session_id)!==job.sandbox_id)fail('TNQD_SANDBOX_CREATE_UNCONFIRMED')
      let ready=false
      for(let i=0;i<30;i++){const s=await this.call(job,'sandbox_status',{session_id:job.sandbox_id});if(s.status==='RUNNING'||s.runnerConnected===true){ready=true;break}await pause(1000)}
      if(!ready)fail('TNQD_SANDBOX_NOT_READY')
      job.phase='UPLOAD_ARTIFACT';this.persist(job)
      const chunkSize=240000
      for(let start=0,index=0;start<content.length;start+=chunkSize,index++) {
        await this.call(job,'sandbox_write_file',{session_id:job.sandbox_id,filepath:'tnqd-upload-'+String(index).padStart(5,'0')+'.txt',contents:content.slice(start,start+chunkSize)})
        job.uploaded_chunks=index+1;this.persist(job)
      }
      for(const [filepath,contents] of Object.entries({'tnqd-binding.json':JSON.stringify({preview_id:job.preview_id,artifact_sha256:job.artifact_sha256,data_mode:job.data_mode}),'tnqd-preview-server.py':readFileSync(new URL('./tnqd-preview-server.py',import.meta.url),'utf8'),'tnqd-testforge.py':readFileSync(new URL('./tnqd-testforge.py',import.meta.url),'utf8')}))
        await this.call(job,'sandbox_write_file',{session_id:job.sandbox_id,filepath,contents})
      const prepare=await this.call(job,'sandbox_shell',{session_id:job.sandbox_id,timeout:90,command:'python tnqd-preview-server.py prepare'})
      if(prepare.exitCode!==0||!String(prepare.stdout).includes(job.artifact_sha256))fail('TNQD_SANDBOX_ARTIFACT_UNCONFIRMED')
      const start=await this.call(job,'sandbox_shell',{session_id:job.sandbox_id,timeout:15,command:'python tnqd-preview-server.py start'})
      if(start.exitCode!==0||!String(start.stdout).includes('TNQD_STARTED'))fail('TNQD_SANDBOX_START_FAILED')
      const binding=await this.remoteHTTP(job,'/__pokedev/binding')
      const actual=JSON.parse(Buffer.from(binding.body_base64,'base64').toString())
      if(binding.status!==200||actual.preview_id!==job.preview_id||actual.artifact_sha256!==job.artifact_sha256)fail('TNQD_PREVIEW_BINDING_MISMATCH')
      job.binding_verified=true;job.phase='LIVE_HTTP';job.state='LIVE';this.persist(job)
    } catch(e){job.state='FAILED';job.error_code=/^TNQD_[A-Z_]+$/.test(e.message)?e.message:'TNQD_SANDBOX_OPERATION_FAILED';job.failure_kind=e.name;this.persist(job)}
  }
  async remoteHTTP(job,path) {
    const encoded=Buffer.from(JSON.stringify({path})).toString('base64')
    const result=await this.call(job,'sandbox_shell',{session_id:job.sandbox_id,timeout:20,command:'python tnqd-preview-server.py proxy '+encoded})
    const line=String(result.stdout??'').split(/\r?\n/).findLast(l=>l.startsWith('TNQD_HTTP:'))
    if(result.exitCode!==0||!line)fail('TNQD_PREVIEW_HTTP_UNCONFIRMED')
    return JSON.parse(line.slice(10))
  }
  async http(id,c) {
    const job=this.read(id,c.scope_id)
    if(job.state!=='LIVE'||job.binding_verified!==true)fail('TNQD_PREVIEW_NOT_LIVE')
    if(typeof c.path!=='string'||c.path.length>1800||!c.path.startsWith('/')||c.path.includes('..')||c.path.includes('\\')||/%2e|%2f|%5c/i.test(c.path))fail('TNQD_PREVIEW_PATH_INVALID')
    if(c.path.startsWith('/api/')) {
      if(!/^\/api\/military-youth\/[A-Za-z0-9_/?=&%.,:+-]*$/.test(c.path)&&!/^\/api\/category[A-Za-z0-9_/?=&%.,:+-]*$/.test(c.path))fail('TNQD_PREVIEW_API_DENIED')
      return this.remoteHTTP(job,c.path)
    }
    let files=this.assets.get(id)
    if(!files){const archive=readFileSync(join(this.root,id+'.zip'));if(sha(archive)!==job.artifact_sha256)fail('TNQD_PREVIEW_CACHE_CHANGED');files=unpackArtifact(archive);this.assets.set(id,files)}
    const path=c.path.split('?')[0]
    const actual=files.has(path)?path:!extname(path)?'/index.html':null
    if(!actual)return {status:404,content_type:'text/plain',body_base64:Buffer.from('Not Found').toString('base64')}
    return {status:200,content_type:MIME[extname(actual)]??'application/octet-stream',body_base64:files.get(actual).toString('base64'),artifact_sha256:job.artifact_sha256}
  }
  test(id,c) {
    const job=this.read(id,c.scope_id)
    if(job.testforge)return job
    if(job.state!=='LIVE'||!this.jobs.has(id))fail('TNQD_PREVIEW_NOT_LIVE')
    const live=this.jobs.get(id);live.testforge={state:'RUNNING',started_at:new Date().toISOString()};this.persist(live)
    void this.runTest(live).catch(()=>{});return this.read(id,c.scope_id)
  }
  async runTest(job) {
    try{
      const result=await this.call(job,'sandbox_shell',{session_id:job.sandbox_id,timeout:180,command:'python tnqd-testforge.py '+job.preview_id})
      const line=String(result.stdout??'').split(/\r?\n/).findLast(s=>s.startsWith('TNQD_TESTFORGE:'))
      if(!line)fail('TNQD_TESTFORGE_RESULT_UNCONFIRMED')
      const report=JSON.parse(line.slice(15))
      if(report.preview_id!==job.preview_id||report.artifact_sha256!==job.artifact_sha256||report.framework!=='TestForge TraceRecorder'||report.total<6)fail('TNQD_TESTFORGE_BINDING_INVALID')
      job.testforge={...report,state:report.passed===report.total?'SUCCEEDED':'FAILED'}
    }catch(e){job.testforge={state:'UNCONFIRMED',error_code:/^TNQD_[A-Z_]+$/.test(e.message)?e.message:'TNQD_TESTFORGE_UNCONFIRMED'}}
    this.persist(job)
  }
}
