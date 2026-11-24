"""Explicit native TaskLoop candidates, separate from cycle/release authority."""
import asyncio
import difflib
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from langflow.adlc.vai_services import PlatformClient, ServiceCheckError, now

ROOT = '/api/v1/pokedev-services/product-loops'
ACTIVE = {'RESERVED', 'RUNNING', 'UNCONFIRMED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class LoopStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS product_loops
                (id TEXT PRIMARY KEY, owner TEXT NOT NULL, delivery TEXT NOT NULL,
                 cycle TEXT NOT NULL, payload TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self, owner, delivery, cycle):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM product_loops WHERE owner=? AND delivery=? AND cycle=? ORDER BY rowid DESC LIMIT 30',
                              (owner, delivery, cycle)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reserve(self, owner, delivery, cycle, identity, context):
        command = {'loop_id': identity, 'scope_id': digest([owner, delivery, cycle]), **context}
        value = {'loop_id': identity, 'scope_id': command['scope_id'], 'request_digest': digest(command),
                 'state': 'RESERVED', 'created_at': now(), 'command': command, 'cycle_id': cycle}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT owner,delivery,cycle,payload FROM product_loops WHERE id=?', (identity,)).fetchone()
            if old:
                if old[:3] != (owner, delivery, cycle) or json.loads(old[3])['request_digest'] != value['request_digest']:
                    raise ServiceCheckError('LOOP_ID_CONFLICT')
                return json.loads(old[3]), False
            rows = db.execute('SELECT payload FROM product_loops WHERE owner=?', (owner,)).fetchall()
            if any(json.loads(row[0])['state'] in ACTIVE for row in rows):
                raise ServiceCheckError('LOOP_ALREADY_ACTIVE')
            db.execute('INSERT INTO product_loops VALUES (?,?,?,?,?)', (identity, owner, delivery, cycle, json.dumps(value)))
        return value, True

    def update(self, identity, change):
        with self.connect() as db:
            value = json.loads(db.execute('SELECT payload FROM product_loops WHERE id=?', (identity,)).fetchone()[0])
            value.update(change)
            db.execute('UPDATE product_loops SET payload=? WHERE id=?', (json.dumps(value), identity))
        return value


def public_loop(row):
    result = {k: v for k, v in row.items() if k != 'command'}
    base = row['command']['files']
    result['diff'] = '\n'.join(''.join(difflib.unified_diff(base.get(path, '').splitlines(keepends=True),
        content.splitlines(keepends=True), fromfile='a/'+path, tofile='b/'+path))
        for path, content in row.get('files', {}).items() if content != base.get(path))
    result['release_status'] = 'REVIEW_REQUIRED'
    result['canonical_cycle_execution'] = False
    return result


class LoopService:
    def __init__(self, store, client=None):
        self.store, self.client = store, client or PlatformClient()
        self.tasks = {}

    async def capabilities(self):
        try:
            return await self.client.request('GET', ROOT+'/capabilities')
        except ServiceCheckError as exc:
            if exc.code == 'VAI_RECEIPT_NOT_FOUND':
                raise ServiceCheckError('LOOP_RUNTIME_UNAVAILABLE', 503) from None
            raise

    def spawn(self, row, *, create=False):
        identity = row['loop_id']
        if identity in self.tasks:
            return
        task = asyncio.create_task(self.follow(row, create=create))
        self.tasks[identity] = task
        task.add_done_callback(lambda _: self.tasks.pop(identity, None))

    def accept(self, row, result):
        if (not isinstance(result, dict) or any(result.get(k) != row.get(k) for k in ('loop_id','scope_id','request_digest'))
                or result.get('state') not in {'RESERVED','RUNNING','UNCONFIRMED','SUCCEEDED','FAILED'}
                or result.get('canonical_cycle_execution') is not False
                or result.get('verification_kind') != 'SANDBOX_PROTECTED_UNITTEST'):
            raise ServiceCheckError('LOOP_RECEIPT_MISMATCH')
        command = row['command']
        files = result.get('files', {})
        if not isinstance(files, dict) or any(p not in command['writable_paths'] or not isinstance(v, str) or len(v.encode()) > 65536
                                              for p, v in files.items()):
            raise ServiceCheckError('LOOP_WRITE_SCOPE_DENIED')
        iterations = result.get('iterations', [])
        if result['state'] == 'SUCCEEDED' and (not iterations or iterations[-1].get('passed') is not True
                or iterations[-1].get('protected_intact') is not True
                or not any(v != command['files'].get(p) for p, v in files.items())):
            raise ServiceCheckError('LOOP_PROOF_INVALID')
        updates = {k: result[k] for k in (
            'state','error_code','baseline','iterations','files','changed_paths','contract','goal_state','model','usage',
            'summary','session_id','sandbox_id','native_turns','completed_at','verification_kind','memory') if k in result}
        updates['error_code'] = result.get('error_code')
        self.store.update(row['loop_id'], updates)

    async def follow(self, row, *, create=False):
        try:
            if create:
                self.store.update(row['loop_id'], {'state': 'UNCONFIRMED'})
                self.accept(row, await self.client.request('POST', ROOT, row['command']))
            for _ in range(280):
                result = await self.client.request('GET', ROOT+'/'+row['loop_id']+'?'+urlencode({'scope_id': row['scope_id']}))
                self.accept(row, result)
                if result['state'] not in ACTIVE:
                    return
                await asyncio.sleep(2)
            raise ServiceCheckError('LOOP_RESULT_STILL_PENDING')
        except ServiceCheckError as exc:
            self.store.update(row['loop_id'], {'state': 'UNCONFIRMED', 'error_code': exc.code})
        except Exception:
            self.store.update(row['loop_id'], {'state': 'UNCONFIRMED', 'error_code': 'LOOP_RESULT_INVALID'})


@lru_cache(maxsize=1)
def product_loops():
    return LoopService(LoopStore(Path(__file__).resolve().parents[2] / 'data/vai-services/product-loops.sqlite3'))
