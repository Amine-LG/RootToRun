"""Phase-5 counterexamples: temporary state and fake API answers; no cluster processes."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from academy import config, environment, kube, labs, ledger


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    def forbidden(*a, **k):
        pytest.fail('Verification tests must not execute cluster tools or subprocesses')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(kube, 'oc', forbidden)
    monkeypatch.setattr(kube, 'helm', forbidden)
    monkeypatch.setattr(kube, 'crc_status', lambda: {})
    monkeypatch.setattr(kube, 'whoami', lambda i: {'connected': True, 'user': i})
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'KUBE_DIR', tmp_path / 'kube')
    monkeypatch.setattr(config, 'cluster_enabled', lambda: True)
    monkeypatch.setattr(ledger, 'DB', tmp_path / 'ledger.db')
    monkeypatch.setattr(environment, 'APPROVALS', tmp_path / 'approvals.json')
    environment.invalidate()
    for identity in ('learner', 'reader', 'admin'):
        identity_file(identity)
    environment.approve('api.training.example')


def identity_file(identity, server='https://api.training.example:6443', insecure=False):
    config.KUBE_DIR.mkdir(exist_ok=True)
    kube.kubeconfig(identity).write_text(yaml.safe_dump({
        'apiVersion': 'v1', 'kind': 'Config',
        'clusters': [{'name': 'c', 'cluster': {'server': server,
            'certificate-authority-data': 'dHJ1c3RlZC1jYQ==', 'insecure-skip-tls-verify': insecure}}],
        'contexts': [{'name': 'ctx', 'context': {'cluster': 'c', 'user': 'u'}}],
        'current-context': 'ctx', 'users': [{'name': 'u', 'user': {'token': 'fake'}}],
    }), encoding="utf-8")


def begin(lab_id):
    env = environment.current()
    return ledger.begin_run(lab_id, env['fingerprint'], env['api'])


def group_command(lab, deletion=False):
    obj = lab.cluster_objects[0]
    text = obj.deleted_by if deletion else obj.created_by
    return obj, next(c for _, c in lab.all_commands() if c.cmd == text)


def test_V01_insecure_auxiliary_identity_cannot_delete(monkeypatch):
    """R03's learner TLS guard does not validate the actual admin transport."""
    rid = begin('lab.review')
    ledger.applied(ledger.intent(rid, 'Group', 'academy-review', '/apis/user.openshift.io/v1/groups/academy-review', scope='cluster', identity='admin'), 'group-uid')
    identity_file('admin', insecure=True)
    assert environment.current()['tls_verified']
    effects = []
    monkeypatch.setattr(ledger, '_delete_with_uid', lambda *a: effects.append(a) or 'not_found')
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert not effects, f'V01: unverified admin transport performed deletion: {effects}'
    assert rep['state'] != 'clean'


def test_V02_reclaim_checks_the_run_target_before_reading_or_patching(monkeypatch):
    rid = begin('lab.review')
    with ledger._db() as db:
        db.execute("INSERT INTO volumes (pv,run_id,namespace,claim,claim_uid,phase) VALUES (?,?,?,?,?,?)", ('retained', rid, 'academy-review', 'data', 'claim-uid', 'released-needs-admin'))
    for identity in ('learner', 'admin', 'reader'):
        identity_file(identity, 'https://api.other.example:6443')
    environment.approve('api.other.example')
    calls = []
    def read(i, args, **kw):
        calls.append(('read', i, args))
        return 'found', {'metadata': {'uid': 'pv-uid', 'resourceVersion': '17'}, 'status': {'phase': 'Released'},
                         'spec': {'claimRef': {'uid': 'claim-uid'}, 'persistentVolumeReclaimPolicy': 'Retain'}}, None
    monkeypatch.setattr(kube, 'read', read)
    monkeypatch.setattr(kube, 'oc', lambda i, a, **kw: calls.append(('patch', i, a)) or kube.Result(a, 0, '', '', 0))
    try:
        ledger.reclaim_volumes(rid, wait_s=0)
    except PermissionError:
        pass
    assert not calls, f'V02: old run reclaimed using the new cluster: {calls}'


def test_V03_accepted_tracked_delete_is_not_confirmed_absence(monkeypatch):
    lab = labs.load()['lab.groups']; obj, cmd = group_command(lab, deletion=True)
    rid = begin(lab.id)
    ledger.applied(ledger.intent(rid, obj.kind, obj.name, obj.path, scope='cluster', identity='admin'), 'group-uid')
    monkeypatch.setattr(ledger, 'uid_of', lambda *a: ('found', 'group-uid'))
    # API accepted deletion; the resource still exists because it has a finalizer.
    monkeypatch.setattr(ledger, '_delete_with_uid', lambda *a: 'found')
    labs.run_tracked(lab, cmd, lambda: pytest.fail('Name-based delete callback must never run'))
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep['state'] != 'clean', f'V03: accepted deletion became verified absence: {rep}'
    assert ledger.effects(rid)[0]['phase'] != 'gone'


def test_V04_tracked_create_timeout_retains_uncertain_intent():
    lab = labs.load()['lab.groups']; obj, cmd = group_command(lab)
    rid = begin(lab.id)
    labs.run_tracked(lab, cmd, lambda: {'code': 124, 'status': 'timeout', 'stdout': '', 'stderr': 'Timed out after server accepted create'})
    e = ledger.find_effect(rid, obj.kind, obj.name)
    assert e['phase'] not in ledger.TERMINAL_OK, f'V04: possibly-created Group permanently retired: {e}'


def test_V05_prepare_does_not_write_to_a_replacement_project(monkeypatch):
    lab = labs.load()['lab.rbac']; rid = begin(lab.id)
    ledger.applied(ledger.intent(rid, 'Project', lab.namespace, '/apis/project.openshift.io/v1/projects/' + lab.namespace), 'original-uid')
    monkeypatch.setattr(environment, 'preflight', lambda l: {'runnable': True})
    monkeypatch.setattr(labs, 'project_state', lambda ns: {'exists': True, 'owned': True, 'phase': 'Active', 'uid': 'replacement-uid'})
    monkeypatch.setattr(ledger, 'uid_of', lambda *a: ('found', 'replacement-uid'))
    monkeypatch.setattr(labs, 'write_files', lambda *a: None)
    monkeypatch.setattr(ledger, 'note_volumes', lambda *a: [])
    writes = []
    monkeypatch.setattr(labs, 'apply', lambda *a, **k: writes.append(a) or [])
    result = labs.prepare(lab)
    assert not writes and not result['ok'], f'V05: old ledger row authorized setup in replacement Project: {writes}'


def test_V06_late_bound_storage_is_recorded_before_claim_deletion(monkeypatch):
    # Real storage lab creates PVC/consumer in learner commands, AFTER prepare's new one-shot scan.
    lab = labs.load()['lab.storage']
    monkeypatch.setattr(environment, 'preflight', lambda l: {'runnable': True})
    def project(l, ns, steps, rid):
        ledger.applied(ledger.intent(rid, 'Project', ns, '/apis/project.openshift.io/v1/projects/' + ns), 'project-uid')
    monkeypatch.setattr(labs, '_ensure_project', project)
    monkeypatch.setattr(labs, 'write_files', lambda *a: None)
    state = {'bound': False, 'claim': True}
    def read(i, args, **kw):
        if args[:2] == ['get', 'pvc']:
            items = [{'metadata': {'name': 'notes-data', 'uid': 'claim-uid'}, 'spec': {'volumeName': 'retained'}}] if state['bound'] and state['claim'] else []
            return 'found', {'items': items}, None
        return 'found', {'metadata': {'uid': 'pv-uid'}, 'status': {'phase': 'Released'},
                         'spec': {'claimRef': {'uid': 'claim-uid'}, 'persistentVolumeReclaimPolicy': 'Retain'}}, None
    monkeypatch.setattr(kube, 'read', read)
    assert labs.prepare(lab)['ok']
    rid = ledger.active_run(lab.id, environment.current()['fingerprint'])
    def consume():
        state['bound'] = True
        return {'code': 0}
    labs.run_tracked(lab, lab.steps[1].commands[0], consume)
    # Integration note: run_tracked now records bindings around every command, so the old intermediate
    # assertion `not ledger.volumes(rid)` (which documented the defect) no longer holds; the final assertion is unchanged.
    assert state['bound']
    # PVC is now removed while practising. Retain PV remains; cleanup-time scan has no binding to read.
    state['claim'] = False
    monkeypatch.setattr(ledger, '_delete_with_uid', lambda *a: 'not_found')
    result = labs.cleanup(lab, wait_s=0)
    assert result['state'] != 'clean' or ledger.volumes(rid), 'V06: late-bound Retain PV lost; cleanup claimed clean'


def test_V07_manual_removal_resolves_an_unknown_unrecorded_uid(monkeypatch):
    rid = begin('lab.review')
    ledger.intent(rid, 'Group', 'academy-review', '/apis/user.openshift.io/v1/groups/academy-review', scope='cluster', identity='admin')
    present = {'yes': True}
    reads = []
    monkeypatch.setattr(ledger, 'uid_of', lambda *a: reads.append(a) or (('found', 'unknown-uid') if present['yes'] else ('not_found', None)))
    ledger.request_cleanup(rid)
    assert ledger.cleanup_pass(rid)['effects'][0]['phase'] == 'unknown'
    present['yes'] = False  # operator performs the action that the report explicitly requests
    rep = ledger.cleanup_pass(rid)
    assert rep['state'] == 'clean', f'V07: manual deletion cannot resolve unknown state: {rep}'


@pytest.mark.parametrize('reason', ['Timeout', 'InternalError'])
def test_V08_server_timeout_does_not_prove_project_creation_was_rejected(monkeypatch, reason):
    lab = labs.load()['lab.rbac']; rid = begin(lab.id)
    monkeypatch.setattr(labs, 'project_state', lambda ns: {'exists': False})
    monkeypatch.setattr(kube, 'oc', lambda i, a, **kw: kube.Result(a, 1, '', f'Error from server ({reason}): request outcome is uncertain', 0, 'ok'))
    assert labs._ensure_project(lab, lab.namespace, [], rid)
    assert ledger.effects(rid)[0]['phase'] not in ledger.TERMINAL_OK, 'V08: server timeout retired a possibly-created Project'


def test_V09_actual_forbidden_project_read_is_unknown_not_clean(monkeypatch):
    lab = labs.load()['lab.rbac']
    monkeypatch.setattr(kube, 'oc', lambda i, a, **kw: kube.Result(a, 1, '', f'Error from server (Forbidden): projects.project.openshift.io "{lab.namespace}" is forbidden', 0, 'ok'))
    # Exercise the REAL project_state/oc_json path, not the R21 fixture's preconstructed exists:null.
    result = labs.cleanup(lab, wait_s=0)
    assert result['state'] == 'unknown', f'V09/R21: actual Forbidden response still claimed absence: {result}'


def test_V13_inline_reset_values_validates_the_effective_defaults(monkeypatch, tmp_path):
    """Accepted boolean spelling must have the same meaning in validation and Helm execution."""
    from types import SimpleNamespace
    from academy import runner
    (tmp_path / 'chart').mkdir()
    lab = SimpleNamespace(namespace='academy-review', files={'README': 'chart'})
    monkeypatch.setattr(labs, 'labfiles_dir', lambda l: tmp_path)
    safe = 'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\n'
    unsafe = 'apiVersion: user.openshift.io/v1\nkind: Group\nmetadata:\n  name: foreign-group\n'
    effects = []
    def helm(identity, args, timeout=None):
        if args[:2] == ['get', 'values']:
            text = 'privileged: false\n'
        elif args[0] == 'get':
            text = safe
        elif args[0] == 'template':
            values = {}
            for i, arg in enumerate(args[:-1]):
                if arg == '-f':
                    values.update(yaml.safe_load(Path(args[i + 1]).read_text(encoding="utf-8")) or {})
            text = unsafe if values.get('privileged', True) else safe
        else:
            assert '--reset-values=true' in args
            effects.append('Group/foreign-group')  # actual upgrade uses new defaults: privileged:true
            text = 'completed'
        return kube.Result(['helm', *args], 0, text, '', 0)
    monkeypatch.setattr(kube, 'helm', helm)
    result = runner.execute('helm upgrade demo lab/chart --reset-values=true -n academy-review', lab=lab)
    assert result.get('refused') and not effects, f'V13: explicit reset validated old values then executed defaults: {effects}'


def test_verified_R05_project_recovery_requires_this_runs_marker(monkeypatch):
    rid = begin('lab.review')
    ledger.intent(rid, 'Project', 'academy-review', '/apis/project.openshift.io/v1/projects/academy-review')
    monkeypatch.setattr(kube, 'read', lambda *a, **kw: ('found', {'metadata': {'uid': 'project-uid', 'annotations': {'openshift.io/description': config.MARKER + ' ' + ledger.run_marker(rid)}}}, None))
    deletions = []
    monkeypatch.setattr(ledger, '_delete_with_uid', lambda *a: deletions.append(a) or 'not_found')
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert rep['state'] == 'clean' and deletions[0][-1] == 'project-uid'
    assert rep['effects'][0]['uid'] == 'project-uid'


def test_verified_R04_adoption_endpoint_requires_training_and_exact_name(monkeypatch):
    from fastapi.testclient import TestClient
    from academy.main import app
    c = TestClient(app, headers={'X-Academy': '1', 'Host': '127.0.0.1'})
    monkeypatch.setattr(labs, 'project_state', lambda ns: {'exists': True, 'owned': True, 'phase': 'Active'})
    monkeypatch.setattr(ledger, 'uid_of', lambda *a: ('found', 'project-uid'))
    deletions = []
    monkeypatch.setattr(ledger, '_delete_with_uid', lambda *a: deletions.append(a) or 'not_found')
    # Integration note: cleanup now also lists PVs (reader) to report unrecorded leftovers; none here.
    monkeypatch.setattr(kube, 'read', lambda i, args, **k: ('found', {'items': []}, None))
    environment.revoke()
    assert c.post('/api/cleanup/adopt', json={'namespace': 'academy-review', 'confirm': 'academy-review'}).status_code == 409
    environment.approve('api.training.example')
    assert c.post('/api/cleanup/adopt', json={'namespace': 'academy-review', 'confirm': 'review'}).status_code == 400
    assert not deletions
    result = c.post('/api/cleanup/adopt', json={'namespace': 'academy-review', 'confirm': 'academy-review'})
    assert result.status_code == 200 and result.json()['state'] == 'clean'
    assert deletions[0][-1] == 'project-uid'


def test_V14_interrupted_intent_does_not_read_another_clusters_admin(monkeypatch):
    rid = begin('lab.review')
    ledger.intent(rid, 'Group', 'academy-review', '/apis/user.openshift.io/v1/groups/academy-review', scope='cluster', identity='admin')
    identity_file('admin', 'https://api.other.example:6443')
    assert not environment.same_cluster('admin')
    reads = []
    monkeypatch.setattr(ledger, 'uid_of', lambda *a: reads.append(a) or ('not_found', None))
    ledger.request_cleanup(rid)
    rep = ledger.cleanup_pass(rid)
    assert not reads, f'V14: interrupted intent queried wrong-cluster admin and reported {rep["state"]}: {reads}'
    assert rep['state'] != 'clean'
