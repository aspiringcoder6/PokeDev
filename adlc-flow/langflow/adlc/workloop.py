"""Owned Workloop DAG runs, pinned factories, scoped preview evidence. No cycle approval authority."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import yaml
from langflow.adlc.product_loop import digest
from langflow.adlc.vai_services import PlatformClient, ServiceCheckError, now, redact, settings

PROJECT = Path(__file__).resolve().parents[3]
SOURCES = PROJECT/'integration-sources/workloop'
DATA = PROJECT/'adlc-flow/data/workloop'
LOCK = json.loads((SOURCES/'source-lock.json').read_text(encoding='utf8'))
ACTIVE = {'RESERVED','RUNNING','UNCONFIRMED'}
MODEL = {'provider':'netmind','model':'zai-org/GLM-5.3-Flash'}
SUPPORTED = {'factory-wilson':{'hello2','pingpong','task-api'},'factory-test':set()}

def runtime_ready():
    for name,pin in LOCK['repositories'].items():
        folder=DATA/'runtime'/name
        try:
            process=subprocess.run(['git','-C',str(folder),'rev-parse','HEAD'],capture_output=True,text=True,timeout=5)
            if process.returncode or process.stdout.strip()!=pin['revision']: return False
            clean=subprocess.run(['git','-C',str(folder),'diff','--quiet','HEAD','--'],capture_output=True,timeout=10)
            if clean.returncode: return False
        except (OSError,subprocess.TimeoutExpired): return False
    return True

def _nodes(tasks):
    rows=[]
    for node in tasks or []:
        if node.get('type') in {'Parallel','Sequential'}: rows.extend(_nodes(node.get('tasks')))
        else: rows.append({'id':str(node['id']),'role':node.get('role','coder')})
    return rows

def catalog():
    factories=[]
    for name in ['factory-wilson','factory-test']:
        folder=DATA/'runtime'/name
        workflows=[]
        for path in sorted((folder/'workflows').glob('*.spec.yaml')):
            try:
                spec=yaml.safe_load(path.read_text(encoding='utf8')) or {}
                nodes=_nodes(spec.get('tasks')) if 'tasks' in spec else [
                    {'id':str(k),'role':v.get('role','coder') if isinstance(v,dict) else 'coder'} for k,v in (spec.get('nodes') or {}).items()]
                identity=path.name.removesuffix('.spec.yaml')
                enabled=identity in SUPPORTED[name] and 0<len(nodes)<=6
                workflows.append({'id':identity,'description':str(spec.get('description',''))[:600],
                    'nodes':nodes,'enabled':enabled,'reason':None if enabled else
                    ('Cần bộ source Workloop và môi trường kiểm thử riêng.' if name=='factory-test' else 'Cần cấu hình source và phạm vi trước khi chạy.')})
            except (ValueError,KeyError,TypeError,yaml.YAMLError):
                workflows.append({'id':path.stem,'description':'','nodes':[],'enabled':False,'reason':'Đặc tả chưa hợp lệ.'})
        factories.append({'id':name,'revision':LOCK['repositories'][name]['revision'],'workflows':workflows})
    return factories

class WorkloopStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS workloop_runs (id TEXT PRIMARY KEY,owner TEXT NOT NULL,delivery TEXT NOT NULL,cycle TEXT NOT NULL,payload TEXT NOT NULL)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db: yield db
        finally: db.close()
    def list(self,owner,delivery,cycle):
        with self.connect() as db:
            rows=db.execute('SELECT payload FROM workloop_runs WHERE owner=? AND delivery=? AND cycle=? ORDER BY rowid DESC LIMIT 20',(owner,delivery,cycle)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def reserve(self,owner,delivery,cycle,identity,context):
        command={'run_id':identity,'scope_id':digest([owner,delivery,cycle]),**context}
        value={**command,'request_digest':digest(command),'state':'RESERVED','created_at':now(),'nodes':[],'events':[]}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT owner,delivery,cycle,payload FROM workloop_runs WHERE id=?',(identity,)).fetchone()
            if old:
                if old[:3]!=(owner,delivery,cycle) or json.loads(old[3])['request_digest']!=value['request_digest']:
                    raise ServiceCheckError('WORKLOOP_ID_CONFLICT')
                return json.loads(old[3]),False
            active=db.execute('SELECT payload FROM workloop_runs').fetchall()
            if any(json.loads(r[0])['state'] in ACTIVE for r in active): raise ServiceCheckError('WORKLOOP_ALREADY_ACTIVE')
            db.execute('INSERT INTO workloop_runs VALUES (?,?,?,?,?)',(identity,owner,delivery,cycle,json.dumps(value)))
        return value,True
    def update(self,identity,change):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM workloop_runs WHERE id=?',(identity,)).fetchone()
            value=json.loads(row[0]);value.update(change)
            db.execute('UPDATE workloop_runs SET payload=? WHERE id=?',(json.dumps(value),identity))
        return value

def public_run(row, relay=None):
    result={k:v for k,v in row.items() if k not in {'scope_id','candidate','request_digest','manifest'}}
    preview=result.get('preview')
    if preview:
        relay_url = relay.url(row) if relay else None
        preview={k:v for k,v in preview.items() if k not in {'scope_id'}}
        if preview.get('access_mode') == 'POKEDEV_RELAY':
            preview={**preview,'url':relay_url}
        try:
            from datetime import datetime,timezone
            if datetime.fromisoformat(preview['expires_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
                preview={**preview,'state':'EXPIRED','url':None}
        except (KeyError,ValueError): pass
        result['preview']=preview
    result['canonical_cycle_execution']=False
    return result

class WorkloopService:
    def __init__(self,store,client=None,data=None):
        self.store=store;self.client=client or PlatformClient();self.data=Path(data or DATA/'runs');self.tasks={}
    async def inventory(self):
        try:
            value=await self.client.request('GET','/dsh-plugin-hub/installed')
            installed=value.get('installed',{});versions=value.get('versions',{});loaded=value.get('loaded',[])
            rows=[]
            for name in sorted(installed):
                version=versions.get(name)
                if isinstance(version,dict): version=version.get('version')
                rows.append({'name':name,'version':version if isinstance(version,str) and re.fullmatch(r'[A-Za-z0-9.+_-]{1,50}',version) else None,
                             'loaded':name in loaded,'runtime_tools':name=='vai-sandbox'})
            return {'plugins':rows,'observed_at':now(),'error_code':None}
        except ServiceCheckError as exc: return {'plugins':[],'observed_at':now(),'error_code':exc.code}
    async def capabilities(self):
        ready=await asyncio.to_thread(runtime_ready)
        try:
            preview=await self.client.request('GET','/api/v1/pokedev-services/previews/capabilities')
        except ServiceCheckError: preview={'ready':False}
        return {'ready':ready,'engine_revision':LOCK['repositories']['workloop']['revision'],'model':MODEL,
                'preview_ready':preview.get('ready') is True and preview.get('relay') is True,'max_nodes':6,'max_duration_seconds':900,
                'token_cost_cap':False}
    def spawn(self,row):
        if row['run_id'] in self.tasks: return
        task=asyncio.create_task(self.execute(row));self.tasks[row['run_id']]=task
        task.add_done_callback(lambda _:self.tasks.pop(row['run_id'],None))
    def observe(self,row):
        path=self.data/row['run_id']/'result.json'
        if path.is_file():
            try:
                result=json.loads(path.read_text(encoding='utf8'))
                if any(result.get(k)!=row.get(k) for k in ['run_id','scope_id','factory','workflow','revisions']):
                    raise ValueError('binding')
                if result.get('state') not in {'RUNNING','SUCCEEDED','FAILED','UNCONFIRMED'}: raise ValueError('state')
                expected={'source','test','preview'} if row['factory']=='pokedev' else set(row.get('node_ids',[]))
                if result['state']=='SUCCEEDED' and (not result.get('nodes')
                        or len(result['nodes'])!=len(expected) or {n.get('id') for n in result['nodes']}!=expected
                        or any(n.get('state') not in {'DONE','DONE_WITH_CONCERNS'} for n in result['nodes'])):
                    raise ValueError('proof')
                if row['factory']=='pokedev' and result['state']=='SUCCEEDED':
                    preview=result.get('preview',{})
                    if (preview.get('state')!='LIVE' or preview.get('source_sha256')!=row['candidate']['source_sha256']
                            or preview.get('scope_id')!=row['candidate']['scope_id'] or preview.get('preview_id')!=row['run_id']
                            or preview.get('tests',{}).get('passed') is not True
                            or preview.get('tests',{}).get('protected_intact') is not True
                            or not preview.get('tests',{}).get('checks')
                            or any(c.get('exit_code')!=0 for c in preview['tests']['checks'])
                            or preview.get('http',{}).get('passed') is not True or len(preview.get('http',{}).get('checks',[]))!=5
                            or any(c.get('passed') is not True for c in preview['http']['checks'])):
                        raise ValueError('preview proof')
                change={k:result[k] for k in ['state','nodes','events','preview','job_id','workspace','engine_status','completed_at','error_code'] if k in result}
                # Bound fields are machine receipts; do not truncate the array of protected checks.
                return self.store.update(row['run_id'],change)
            except (ValueError,KeyError,OSError,TypeError):
                return self.store.update(row['run_id'],{'state':'UNCONFIRMED','error_code':'WORKLOOP_RECEIPT_INVALID'})
        return row
    async def execute(self,row):
        identity=row['run_id'];directory=self.data/identity
        try:
            directory.mkdir(parents=True,exist_ok=False)
            manifest={k:row[k] for k in ['run_id','scope_id','factory','workflow','revisions','model','candidate'] if k in row}
            (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
            base,token=settings()
            env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','COMSPEC','PATHEXT'}}
            env.update(DSH_URL=base,DSH_TOKEN=token,PYTHONUTF8='1',PYTHONUNBUFFERED='1')
            self.store.update(identity,{'state':'RUNNING'})
            with (directory/'worker.log').open('wb') as log:
                child=await asyncio.create_subprocess_exec(sys.executable,'-X','utf8',str(SOURCES/'worker.py'),str(directory/'manifest.json'),
                     env=env,stdout=log,stderr=log,cwd=str(PROJECT))
                await asyncio.wait_for(child.wait(),timeout=930)
            result=self.observe(row)
            if result['state'] in {'RESERVED','RUNNING'}:
                imported=(directory/'result.json').is_file()
                self.store.update(identity,{'state':'UNCONFIRMED' if imported else 'FAILED',
                    'error_code':'WORKLOOP_WORKER_STOPPED' if imported else 'WORKLOOP_RUNTIME_IMPORT_FAILED'})
        except Exception:
            self.store.update(identity,{'state':'UNCONFIRMED','error_code':'WORKLOOP_START_UNCONFIRMED'})

@lru_cache(maxsize=1)
def workloops(): return WorkloopService(WorkloopStore(DATA/'runs.sqlite3'))
