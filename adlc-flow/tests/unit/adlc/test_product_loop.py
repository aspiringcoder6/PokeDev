import pytest
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from langflow.adlc.product_loop import LoopService, LoopStore, public_loop
from langflow.adlc.vai_services import ServiceCheckError


def context():
    return {'base_commit': 'a'*40, 'goal': 'Implement app', 'files': {'app.py': '', 'test_acceptance.py': 'protected'},
            'writable_paths': ['app.py'], 'checks': [{'check_id': 'acceptance', 'test_path': 'test_acceptance.py', 'timeout_ms': 30000}],
            'max_iterations': 3}


def test_reservation_owner_scope_idempotency_and_restart(tmp_path):
    path = tmp_path/'loops.sqlite3'
    store = LoopStore(path)
    first, fresh = store.reserve('owner', 'delivery', 'cycle', 'id', context())
    assert fresh
    assert LoopStore(path).reserve('owner', 'delivery', 'cycle', 'id', context()) == (first, False)
    assert store.list('other', 'delivery', 'cycle') == []
    with pytest.raises(ServiceCheckError, match='CONFLICT'):
        store.reserve('other', 'delivery', 'cycle', 'id', context())
    with pytest.raises(ServiceCheckError, match='ACTIVE'):
        store.reserve('owner', 'delivery', 'cycle', 'second', context())


def test_receipt_cannot_claim_pass_without_source_delta_and_protected_checks(tmp_path):
    store = LoopStore(tmp_path/'loops.sqlite3')
    row, _ = store.reserve('owner','delivery','cycle','id',context())
    service = LoopService(store)
    receipt = {k: row[k] for k in ('loop_id','scope_id','request_digest')}
    receipt.update(state='SUCCEEDED', canonical_cycle_execution=False, verification_kind='SANDBOX_PROTECTED_UNITTEST',
                   files={'app.py': 'actual change'}, iterations=[{'passed': True, 'protected_intact': True}])
    service.accept(row, receipt)
    value = store.list('owner','delivery','cycle')[0]
    assert '+actual change' in public_loop(value)['diff']
    assert 'command' not in public_loop(value)
    for update, code in [({'files': {'app.py': ''}}, 'PROOF'),
                         ({'files': {'test_acceptance.py': 'pass'}}, 'SCOPE'),
                         ({'scope_id': 'other'}, 'MISMATCH'),
                         ({'iterations': [{'passed': True, 'protected_intact': False}]}, 'PROOF')]:
        with pytest.raises(ServiceCheckError, match=code):
            service.accept(row, {**receipt, **update})


@pytest.mark.asyncio
async def test_ambiguous_create_never_gets_reposted_on_recovery(tmp_path):
    class Client:
        def __init__(self):
            self.calls = []
        async def request(self, method, path, body=None):
            self.calls.append(method)
            raise ServiceCheckError('VAI_PLATFORM_UNAVAILABLE')
    store = LoopStore(tmp_path/'loops.sqlite3')
    row, _ = store.reserve('owner','delivery','cycle','id',context())
    client = Client()
    service = LoopService(store, client)
    await service.follow(row, create=True)
    assert store.list('owner','delivery','cycle')[0]['state'] == 'UNCONFIRMED'
    await LoopService(LoopStore(store.path), client).follow(row)
    assert client.calls == ['POST', 'GET']


@pytest.mark.parametrize('tamper', [False, True])
def test_fixed_runner_executes_real_unittest_and_detects_protected_file_tampering(tmp_path, tamper):
    runner = Path(__file__).resolve().parents[4] / 'integration-sources/pokedev-services-plugin/lib/loop-verifier.py'
    (tmp_path/'pokedev-verify.py').write_bytes(runner.read_bytes())
    source = 'VALUE = 7\n'
    if tamper:
        source += "from pathlib import Path\nPath('test_acceptance.py').write_text('# tampered')\n"
    (tmp_path/'app.py').write_text(source, encoding='utf8')
    protected = 'import unittest\nfrom app import VALUE\nclass Check(unittest.TestCase):\n def test_real(self): self.assertEqual(VALUE,7)\n'
    (tmp_path/'test_acceptance.py').write_bytes(protected.encode())
    (tmp_path/'pokedev-checks.json').write_text(json.dumps({'protected': {'test_acceptance.py': hashlib.sha256(protected.encode()).hexdigest()},
        'checks': [{'check_id': 'acceptance','test_path': 'test_acceptance.py','timeout_ms': 10000}]}), encoding='utf8')
    outcome = subprocess.run([sys.executable,'-I','pokedev-verify.py'],cwd=tmp_path,capture_output=True,check=True)
    report = json.loads((tmp_path/'pokedev-check-result.json').read_text(encoding='utf8'))
    assert report['passed'] is not tamper
    assert report['protected_intact'] is not tamper
    assert 'Ran 1 test' in report['checks'][0]['stderr']


@pytest.mark.asyncio
async def test_native_api_checks_owner_and_cycle_before_platform_access(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException, Response
    from langflow.api.v1 import adlc_product_loop as api
    from uuid import uuid4
    source = AsyncMock(side_effect=HTTPException(404))
    monkeypatch.setattr(api, 'source', source)
    monkeypatch.setattr(api, 'product_loops', lambda: pytest.fail('No platform access before authorization'))
    with pytest.raises(HTTPException):
        await api.list_loops(uuid4(),uuid4(),AsyncMock(),object(),Response())
