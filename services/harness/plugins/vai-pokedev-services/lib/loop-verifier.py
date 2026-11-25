"""Fixed runner: protected unittest files are checked before and after the child."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

config = json.loads(Path('pokedev-checks.json').read_text(encoding='utf8'))
protected = config['protected']


def intact():
    return all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
               for name, digest in protected.items())


results = []
before = intact()
for check in config['checks']:
    try:
        test_file = Path(check['test_path'])
        outcome = subprocess.run([sys.executable, '-I', '-m', 'unittest', 'discover',
                                  '-s', str(test_file.parent), '-p', test_file.name, '-t', '.', '-v'],
                                 capture_output=True, text=True, encoding='utf8', errors='replace',
                                 timeout=min(check['timeout_ms'] / 1000, 60))
        results.append({'check_id': check['check_id'], 'exit_code': outcome.returncode,
                        'stdout': outcome.stdout[-10000:], 'stderr': outcome.stderr[-10000:]})
    except subprocess.TimeoutExpired:
        results.append({'check_id': check['check_id'], 'exit_code': -1,
                        'stdout': '', 'stderr': 'CHECK_TIMEOUT'})
after = intact()
report = {'checks': results, 'protected_intact': before and after,
          'passed': before and after and bool(results) and all(row['exit_code'] == 0 for row in results)}
Path('pokedev-check-result.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf8')
print('POKEDEV_LOOP_CHECK:' + json.dumps(report, ensure_ascii=False))
