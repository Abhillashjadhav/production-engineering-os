"""Reproduce tamper rejection and a separate non-product extension fixture."""

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

from pmpe.barebones import _verify_snapshot, _workspace_snapshot, compile_barebones_plan
from pmpe.contracts.authoring import build_contract_draft

REPO = Path(__file__).resolve().parents[3]
PACKET = Path(sys.argv[1]).resolve()
EVIDENCE = Path(__file__).resolve().parent
ENTRY = REPO / 'examples/barebones/contract-file.py'
spec = importlib.util.spec_from_file_location('contract_file', ENTRY)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
freeze_digest = (PACKET / 'freeze-bundle.sha256').read_text().strip()
roots = {'PM-agent-OS': PACKET.parents[1], 'production-engineering-os': REPO}
profile = entry.read_json(PACKET / 'execution-profile.json')

# Alter only a disposable replica of all PMOS-bound artifacts; preserve originals.
with tempfile.TemporaryDirectory(prefix='pmos-tamper-replica-') as temporary:
    clone = Path(temporary)
    manifest = entry.read_json(PACKET / 'freeze-manifest.json')
    for item in manifest['artifacts']:
        if item['repository'] == 'PM-agent-OS':
            target = clone / item['path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(roots['PM-agent-OS'] / item['path'], target)
    replica = clone / PACKET.relative_to(roots['PM-agent-OS'])
    shutil.copy2(PACKET / 'freeze-manifest.json', replica / 'freeze-manifest.json')
    guard = entry.DigestGuard(replica / 'freeze-manifest.json',
                              {**roots, 'PM-agent-OS': clone}, freeze_digest,
                              EVIDENCE / 'tamper/contract/digest-checks.jsonl')
    guard.check('before-control')
    modified = replica / 'contract.approved.json'
    data = entry.read_json(modified); data['desired_outcome'] = 'Altered without owner approval'
    entry.write_json(modified, data)
    try:
        guard.check('before-authoritative-check')
    except entry.TamperDetectedError as exc:
        entry.write_json(EVIDENCE / 'tamper/contract/result.json',
                         {'rejected': True, 'candidate_executed': False,
                          'modified_replica_sha256': entry.digest(modified), 'error': str(exc)})
    else:
        raise AssertionError('Changed approval-bound artifact passed')

# A replaced candidate evaluator is detected before its first process starts.
with tempfile.TemporaryDirectory(prefix='evaluator-replacement-') as temporary:
    candidate = Path(temporary) / 'candidate'
    shutil.copytree(EVIDENCE / 'live/candidate', candidate)
    evaluator = candidate / 'tests/acceptance/task_tracker.py'
    evaluator.write_text('def observe(**kwargs): return {"claimed_pass": True}\n')
    guard = entry.DigestGuard(PACKET / 'freeze-manifest.json', roots, freeze_digest,
                              EVIDENCE / 'tamper/evaluator/digest-checks.jsonl')
    template = entry.load_template(PACKET / 'bindings.json')
    plan = compile_barebones_plan(contract=entry.read_json(PACKET / 'contract.approved.json'),
                                  repository_root=REPO, template=template)
    execution = entry.HostExecution(guard, template, profile['resource_caps'], plan.criteria,
                                    EVIDENCE / 'tamper/evaluator/processes.jsonl')
    try:
        _verify_snapshot(plan, _workspace_snapshot(candidate), template, execution)
    except entry.TamperDetectedError as exc:
        entry.write_json(EVIDENCE / 'tamper/evaluator/result.json',
                         {'rejected': True, 'candidate_executed': execution.log.exists(),
                          'modified_evaluator_sha256': entry.digest(evaluator), 'error': str(exc)})
        assert not execution.log.exists()
    else:
        raise AssertionError('Replaced evaluator passed')

# Independent binding fixture: a new business-action identifier, no engine edit,
# no model and no claim that the owner approved a second product.
fixture = EVIDENCE / 'extension'; fixture.mkdir(exist_ok=False)
answers = copy.deepcopy(entry.read_json(PACKET / 'publisher-input.json'))
answers.update({
    'contract_id': 'EXTENSION-FIXTURE-001', 'product_name': 'Unapproved extension fixture',
    'scope': ['Fixture only: echo a supplied greeting through a new action identifier.'],
    'functional_requirements': [{'id': 'FR-001', 'title': 'Echo fixture',
                                  'description': 'Return the supplied greeting.', 'capability': 'greeting.echo'}],
    'acceptance_criteria': [{'id': 'AC-001', 'requirement': 'FR-001',
                            'criterion': 'Fixture echoes hello unchanged.',
                            'given': [{'path': 'fixture.ready', 'operator': 'eq', 'value': True}],
                            'when': {'action': 'greeting.echo', 'arguments': {'message': 'hello'}},
                            'then': [{'path': 'result.message', 'operator': 'eq', 'value': 'hello'}]}],
    'binary_release_gates': [{'id': 'GATE-001', 'description': 'Fixture assertion passes.'}],
    'golden_cases': ['Fixture echoes hello unchanged.'],
    'approved_product_decisions': [{'id':'APD-001','decision':'Test fixture only; no product approval claimed.'}],
})
draft = build_contract_draft(answers); assert draft.draft and draft.draft['contract_status'] == 'DRAFT'
entry.write_json(fixture / 'contract.draft.json', draft.draft)
bindings = {'version': 'greeting-fixture-v1', 'files': {
    'tests/__init__.py': '', 'tests/acceptance/__init__.py': '',
    'tests/acceptance/greeting.py': 'def echo(message):\n    return {"message": message}\n'},
    'actions': {'greeting.echo': 'tests.acceptance.greeting:echo'},
    'context': {'fixture': {'ready': True}}}
entry.write_json(fixture / 'bindings.json', bindings)
template = entry.load_template(fixture / 'bindings.json')
plan = compile_barebones_plan(contract=draft.draft, repository_root=REPO, template=template)
guard = entry.DigestGuard(PACKET / 'freeze-manifest.json', roots, freeze_digest,
                          fixture / 'digest-checks.jsonl')
execution = entry.HostExecution(guard, template, profile['resource_caps'], plan.criteria,
                                fixture / 'processes.jsonl')
with guard.boundary('extension-fixture', {fixture / 'bindings.json': entry.digest(fixture / 'bindings.json'),
                                        fixture / 'contract.draft.json': entry.digest(fixture / 'contract.draft.json')}):
    findings = _verify_snapshot(plan, {p:s.encode() for p,s in template.files.items()}, template, execution)
assert not findings, findings
entry.write_json(fixture / 'result.json', {'fixture_only': True, 'owner_product_approval': False,
                 'new_business_action': 'greeting.echo', 'criteria_passed': 1,
                 'engine_source_changes': 0, 'model_calls': 0, 'findings': []})
print('PASS: changed approved-contract replica rejected; evaluator replacement rejected before execution; new greeting.echo binding executed unchanged engine.')
