# Independent R3 replay evidence review

Date: 2026-09-24. Scope: read-only verification of the regenerated retained,
persistence and filtering evidence and the original frozen v1 packet. The only
file written by this review is this report. No candidate, provider, approval,
publisher, paid API or permission-changing operation was executed.

**Verdict: the regenerated evidence is complete and internally consistent with
the unchanged frozen criteria and source inventory.** This is verification of
retained observations, not an independent rerun of the candidate or a new gated
engineering run.

| Case | Ordered digest boundaries | Process records | Recorded observations, independently checked |
| --- | ---: | ---: | --- |
| retained | 30 | 14 | All 14 criteria PASS |
| persistence | 30 | 14 | AC-002/003/004/005/006/007/009/010/013/014 FAIL |
| filtering | 30 | 14 | AC-004/005 FAIL |

All failures are `ASSERTION_FAILED`; all observer processes exited successfully.
Exact module/function/arguments, process indexes, assertion results and summary
counts agree. Every recorded inventory digest was independently reconstructed:
220 entries at command boundaries and 223 at criterion boundaries, including
the temporary protected test paths. All 90 observed inventories match their
expected inventories. The 218 freeze-manifest and 212 review-manifest entries
match current file bytes. The original approval receipt verifies for the owner
recorded in the packet, Abhillash Jadhav. The canonical loader passes, the
historical compiler reproduces the frozen plan, publisher-input criteria equal
approved criteria, and evaluator bytes equal the frozen template binding.

The supplied completeness checker checks sequence and record presence; it does
not itself reconstruct the expected inventory or evaluate the recorded stdout.
The additional read-only probe below performs those checks.

## Exact identities

| Identity | SHA-256 |
| --- | --- |
| Approved contract, canonical | `sha256:501e0fd5eae05bceffeef928d1b731173dd8be87c988340f2761575d29b7e80e` |
| Approved contract, raw bytes | `sha256:41f93f23ca57cef11201fe685b18d66be882c122e5a3c7192e37e9018de0f0e2` |
| Receipt's verified `receipt_digest` field | `sha256:4b1f17711268f9bceca6d7b4fd4082bc35a65ddee383c6eb7eee28b5a64609ef` |
| Submitted receipt, raw bytes | `sha256:856ef2b3257a54c3834c44f95d61b245be4906807db50d2f88dc63e219b1d09c` |
| Freeze manifest, canonical anchor | `sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2` |
| Review manifest, canonical | `sha256:fbfe73637ec326330d3107aac1d43b023fc7c5473fe3ef7dfcede7e4d07af711` |
| Compiled plan's `plan_digest` field | `sha256:1dad520ebc6ac6973aeb23d80fe5c98d67e3d8a5fa20d902f56d45a180777b28` |
| Evaluator, raw bytes | `sha256:7a5a3064d8ec07ae1d941aaa2145330076c8acf62bbbc7cc65e158b9f9cf4d66` |
| Execution profile, raw bytes | `sha256:4a46f594d269e130b8933cd032fa7fb400c0a510553f77140efa2a1fab683120` |
| Historical adapter, raw bytes | `sha256:08d590186663d48a1ecfd34cb169240d07c9d65e132e4791c6816171f7ccf387` |
| Completeness checker, raw bytes | `sha256:364f78fdf8e2e676ecc5616f54d1a32ce760153cd1e255d0854073b26f8990f6` |

## Commands executed

Working directory for these three commands:
`/workspace/scratch/f9ac546f3a50/integration-20260924/peos-proof`.
Each exited zero and returned 30 observations, 14 process records and zero
digest mismatches.

```sh
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B docs/evidence/r3-repair-20260924/check_replay_complete.py docs/evidence/integration-review-20260924/retained
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B docs/evidence/r3-repair-20260924/check_replay_complete.py docs/evidence/integration-review-20260924/persistence
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B docs/evidence/r3-repair-20260924/check_replay_complete.py docs/evidence/integration-review-20260924/filtering
```

Additional read-only probe, executed successfully as shown. It imports pure
compiler/assertion helpers but never calls a runner or evaluates candidate code.

```sh
/workspace/scratch/f9ac546f3a50/overnight-20260923/venv/bin/python -B - <<'PY'
import ast, hashlib, json, re, sys
from pathlib import Path
pmos=Path('/workspace/scratch/f9ac546f3a50/integration-20260924/pmos-approved')
peos=Path('/workspace/scratch/f9ac546f3a50/integration-20260924/peos-proof')
packet=pmos/'reviews/task-tracker-v1'
evidence=peos/'docs/evidence/integration-review-20260924'
sys.path.insert(0,str(peos/'src'))
from pmpe.contracts.canonical import canonical_digest
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.model import load_contract
from pmpe.barebones import Template, compile_barebones_plan, _assertion_passes
from pmpe.contracts.acceptance import PropertyAssertion
sha=lambda b:'sha256:'+hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_bytes())
roots={'PM-agent-OS':pmos,'production-engineering-os':peos}
freeze=read(packet/'freeze-manifest.json')
for name in ['freeze-manifest.json','review-manifest.json']:
 manifest=read(packet/name)
 failures=[e for e in manifest['artifacts'] if sha((roots[e['repository']]/e['path']).read_bytes())!=e['sha256']]
 assert not failures
 print(json.dumps({'manifest':name,'artifacts':len(manifest['artifacts']),'all_match':True}))
assert canonical_digest(freeze)==(packet/'freeze-bundle.sha256').read_text().strip()
contract=read(packet/'contract.approved.json')
receipt=read(packet/'approval-receipt.json')
assert verify_contract_approval(contract,receipt,expected_approver=freeze['owner'])==receipt['receipt_digest']
assert load_contract(packet/'contract.approved.json').runnable
bindings=read(packet/'bindings.json'); template=Template(**bindings)
assert (packet/'evaluator.py').read_bytes()==template.files['tests/acceptance/task_tracker.py'].encode()
plan=compile_barebones_plan(contract=contract,repository_root=peos,template=template)
assert canonical_digest(plan.as_dict())==canonical_digest(read(packet/'compiled-plan.json'))
assert contract['acceptance_criteria']==read(packet/'publisher-input.json')['acceptance_criteria']
print(json.dumps({'original_contract_canonical':canonical_digest(contract),'original_contract_raw':sha((packet/'contract.approved.json').read_bytes()),'freeze':canonical_digest(freeze),'plan_digest':plan.plan_digest,'evaluator_bytes_match':True,'criteria_unchanged':True,'approval_verified':True}))
entry=peos/'examples/barebones/contract-file.py'; entry_hash=sha(entry.read_bytes())
base=[(str((roots[e['repository']]/e['path']).resolve()),e['sha256']) for e in freeze['artifacts']]
base.append((str((packet/'freeze-manifest.json').resolve()),sha((packet/'freeze-manifest.json').read_bytes())))
for case in ['retained','persistence','filtering']:
 directory=evidence/case
 result=read(directory/'result.json')
 boundaries=[json.loads(x) for x in (directory/'digest-checks.jsonl').read_text().splitlines()]
 processes=[json.loads(x) for x in (directory/'processes.jsonl').read_text().splitlines()]
 source=read(directory/'execution-source.json'); compatibility=read(directory/'compatibility.json')
 assert source['entry_digest']==entry_hash and source['freeze_digest']==canonical_digest(freeze)
 assert compatibility['plan_digest']==plan.plan_digest
 for record in [boundaries[0],boundaries[-1]]:
  expected=base+[(str(entry.resolve()),entry_hash)]
  assert record['checked']==len(expected)==220
  assert record['expected_inventory_digest']==record['observed_inventory_digest']==canonical_digest(expected)
 semantic={}
 for index,(c,process) in enumerate(zip(plan.criteria,processes,strict=True)):
  assert process['criterion_id']==c.criterion_id and process['check_index']==index
  assert process['exit_code']==0 and process['stderr']==''
  sourcecode=process['argv'][12] if len(process['argv'])>12 else ''
  sourcecode=next(s for s in process['argv'] if "sys.path.insert(0," in s)
  workspace=ast.literal_eval(re.search(r'sys.path.insert\(0,(.*?)\);',sourcecode).group(1))
  protected=[(str(Path(workspace)/relative),sha(content.encode())) for relative,content in template.files.items() if relative.startswith('tests/')]
  protected.append((str(entry.resolve()),entry_hash))
  expected=base+protected
  for record in boundaries[1+2*index:3+2*index]:
   assert record['checked']==len(expected)==223
   assert record['expected_inventory_digest']==record['observed_inventory_digest']==canonical_digest(expected)
  observation=json.loads(process['stdout'])
  if c.form=='measure':
   target=template.measures[c.measure]
   assert process['argv'][-3:-1]==target.split(':') and json.loads(process['argv'][-1])=={}
   assert type(observation['sample_size']) is int
   passed=observation['sample_size']>=c.minimum_sample and _assertion_passes(PropertyAssertion('value',c.operator,c.value),observation)
  else:
   target=template.actions[c.when.action]
   assert process['argv'][-3:-1]==target.split(':') and json.loads(process['argv'][-1])==dict(c.when.arguments)
   passed=all(_assertion_passes(x,template.context) for x in c.given) and all(_assertion_passes(x,{'result':observation}) for x in c.then)
  semantic[c.criterion_id]='PASS' if passed else 'FAIL'
 assert semantic==result['criteria']
 failed=[c for c,status in semantic.items() if status=='FAIL']
 assert {f['subject_id'] for f in result['findings']}==set(failed)
 assert all(f['code']=='ASSERTION_FAILED' for f in result['findings'])
 summary=read(evidence/'replay-summary.json')['cases'][case]
 assert summary['fail_ids']==failed and summary['pass_count']==14-len(failed)
 print(json.dumps({'case':case,'boundaries':len(boundaries),'processes':len(processes),'inventories_independently_recomputed':True,'all_process_observations_match_frozen_criteria':True,'pass_count':14-len(failed),'fail_ids':failed,'failure_class':'ASSERTION_FAILED only' if failed else 'none'}))
PY
```

## Migration proposal findings

These are proposal-review findings, not findings against an implemented v2.

1. Section 6.4 introduces a hash cycle: the contract embeds the digest of a
   manifest that hashes the contract, receipt and plan. A two-step freeze cannot
   resolve that cycle. Bind a separate immutable source/input inventory in the
   contract, then bind contract/receipt/plan/inventory in an outer packet identity.
2. Provenance must require exact reconstructed snapshot equality: frozen
   template bytes plus every successfully applied response in ledger order,
   including prior attempts. Path subsets and equality only on changed files
   miss edits/deletions of unchanged template or evaluator files.
3. The complete command-after boundary must precede PASS evidence and release
   readiness. Distinguish phases, attempts and mutants; repeated bare criterion
   IDs and an expected sequence derived solely from observed passes are weak.
4. Unknown sandboxes stay blocked or NOT_EVALUATED. A class name, subclass or
   unchecked isolation report cannot establish Bubblewrap/full isolation.
5. Negative controls need exact candidate/mutant identities, protected evaluator
   bytes, complete criterion results and assertion-only intended failures.
   Minimum failing-ID subsets demonstrate sensitivity, not semantic isolation
   of the human-authored mutation.
6. Fresh mode remains a provider declaration; fixture tests do not prove a live
   model. Unsigned receipts, root tampering and fully re-chainable retained
   evidence remain limits. An independently retained head digest is required
   for an external evidence anchor.

Historical replay remains weaker-isolation retained evidence. This report does
not claim live generation, OS isolation, authentic owner signatures, resistance
to a root writer, or compatibility of v1 with the changed release-gate engine.
