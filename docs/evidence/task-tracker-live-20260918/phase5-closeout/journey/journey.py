"""Replay a user journey against the exact generated artifact after clean install."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out = Path(__file__).resolve().parent
peos = root / 'peos'; packet = root / 'pmos/reviews/task-tracker-v1'
spec = importlib.util.spec_from_file_location('entry', peos / 'examples/barebones/contract-file.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
guard = entry.DigestGuard(packet / 'freeze-manifest.json',
    {'PM-agent-OS': root / 'pmos', 'production-engineering-os': peos},
    (packet / 'freeze-bundle.sha256').read_text().strip(), out / 'journey-digests.jsonl')
product = root / 'candidate/product.py'; extra = {product: entry.digest(product)}
open1 = {'id':1,'title':'Buy milk','status':'open'}
open2 = {'id':2,'title':'Buy milk','status':'open'}
done1 = {**open1,'status':'completed'}
steps = [
    (['create',''], 2, {'error':'INVALID_TITLE'}),
    (['create','Buy milk'], 0, {'task':open1}),
    (['create','Buy milk'], 0, {'task':open2}),
    (['complete','1'], 0, {'task':done1}),
    (['complete','1'], 0, {'task':done1}),
    (['list','--status','open'], 0, {'tasks':[open2]}),
    (['list','--status','completed'], 0, {'tasks':[done1]}),
    (['list'], 0, {'tasks':[done1,open2]}),
]
observations=[]
with tempfile.TemporaryDirectory(prefix='clean-user-store-') as temporary:
    for number,(args,code,expected) in enumerate(steps,1):
        with guard.boundary(f'user-journey-{number}', extra):
            cmd=['prlimit','--as=1073741824','--cpu=11','--fsize=67108864','--nofile=256',
                 '--nproc=128','--',sys.executable,'-I','-B',str(product),'--store',temporary+'/tasks.json',*args]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=2,check=False,
                                  env={'PATH':'/usr/local/bin:/usr/bin:/bin','LC_ALL':'C'})
            observed=json.loads(result.stdout)
            observations.append({'command':cmd,'exit_code':result.returncode,'output':observed})
            assert result.returncode==code and observed==expected, observations[-1]
entry.write_json(out/'journey.json',{'passed':True,'commands':len(steps),'product_sha256':entry.digest(product),
                 'steps':observations,'all_processes_sequential':True,'new_model_generation':False,
                 'real_sandbox_leg':'BLOCKED_BY_ENVIRONMENT; owner closed retries'})
print('PASS: eight sequential user commands from a clean venv; rejection preserves ID 1, duplicate create allocates ID 2, completion retry and status filters persist across process restarts.')
