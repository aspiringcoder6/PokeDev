"""Install reviewed Workloop sources in a private cache, without changing PokeDev dependencies."""
import base64
import json
import os
import subprocess
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads(Path(__file__).with_name('source-lock.json').read_text(encoding='utf8'))
CACHE = ROOT/'adlc-flow/data/workloop/runtime'

def main():
    cfg = dotenv_values(ROOT/'.env.vai-platform.local')
    base = cfg['VAI_GITEA_URL'].rstrip('/')
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith('GIT_TRACE') or key in {'GIT_CURL_VERBOSE','GIT_CONFIG_COUNT'}:
            environment.pop(key,None)
    basic = base64.b64encode((cfg.get('VAI_GITEA_USER','admin')+':'+cfg['VAI_GITEA_TOKEN']).encode()).decode()
    environment.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='http.extraHeader',
                       GIT_CONFIG_VALUE_0='Authorization: Basic '+basic,GIT_TERMINAL_PROMPT='0')
    CACHE.mkdir(parents=True,exist_ok=True)
    for name, pin in LOCK['repositories'].items():
        target = CACHE/name
        def git(*args, auth=False):
            p = subprocess.run(['git','-c','core.hooksPath=','-c','credential.helper=',*args],
                               env=environment if auth else None,capture_output=True,text=True,timeout=120)
            if p.returncode: raise RuntimeError('Workloop source operation failed: '+name)
            return p.stdout.strip()
        if not target.exists():
            git('-c','http.followRedirects=false','clone','--no-checkout','--single-branch','--branch',pin['branch'],
                base+'/'+pin['path']+'.git',str(target),auth=True)
            git('-C',str(target),'checkout','--detach',pin['revision'])
        if git('-C',str(target),'rev-parse','HEAD') != pin['revision'] or git('-C',str(target),'status','--porcelain','--untracked-files=no'):
            raise RuntimeError('Cached source differs from reviewed pin: '+name)
        print(json.dumps({'repository':name,'revision':pin['revision'],'ready':True}),flush=True)

if __name__ == '__main__': main()
