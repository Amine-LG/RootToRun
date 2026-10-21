"""Adversarial regressions. Each test names a report finding and asserts the SAFE behaviour.
All process/cluster entry points are stubbed: these tests never run oc, crc or helm.
"""
import json
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

from academy import config, environment, kube, labs, ledger, recorder


@pytest.fixture(autouse=True)
def no_cluster(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('Review tests must not execute a process or contact a cluster')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(kube, 'oc', forbidden)
    monkeypatch.setattr(kube, 'helm', forbidden)
    monkeypatch.setattr(kube, 'crc_status', lambda: {})
    monkeypatch.setattr(kube, 'whoami', lambda i: {'connected': True})
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'KUBE_DIR', tmp_path/'kube')
    monkeypatch.setattr(config, 'RECORDINGS_DIR', tmp_path/'recordings')
    monkeypatch.setattr(environment, 'APPROVALS', tmp_path/'approvals.json')
    monkeypatch.setattr(ledger, 'DB', tmp_path/'ledger.db')
    monkeypatch.setattr(config, 'cluster_enabled', lambda: True)
    environment.invalidate()


def write_identity(identity, server='https://api.training.example:6443', insecure=False):
    config.KUBE_DIR.mkdir(exist_ok=True)
    doc={'apiVersion':'v1','kind':'Config','clusters':[{'name':'c','cluster':{'server':server,'certificate-authority-data':'dHJ1c3RlZC1jYQ==','insecure-skip-tls-verify':insecure}}],
         'contexts':[{'name':'ctx','context':{'cluster':'c','user':'u'}}], 'current-context':'ctx','users':[{'name':'u','user':{'token':'fake'}}]}
    kube.kubeconfig(identity).write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_R01_approval_is_revoked_when_tls_verification_is_disabled():
    write_identity('learner')
    assert environment.approve('api.training.example')['class']=='training'
    write_identity('learner',insecure=True)
    assert environment.current()['class']=='read-only', 'R01: insecure TLS retained a training approval'


def test_R02_elevated_setup_cannot_use_an_admin_on_another_cluster(monkeypatch):
    write_identity('learner');write_identity('admin','https://api.production.example:6443')
    environment.approve('api.training.example')
    assert not environment.same_cluster('admin')
    lab=labs.load()['lab.quotas-limits']
    monkeypatch.setattr(labs,'_ensure_project',lambda *a,**k:None)
    monkeypatch.setattr(labs,'write_files',lambda *a:None)
    effects=[]
    monkeypatch.setattr(labs,'apply',lambda ns,docs,identity='learner':effects.append((identity,docs)) or [])
    result=labs.prepare(lab,elevated=True)
    assert not any(i=='admin' for i,d in effects), f'R02: wrong-cluster admin effects: {effects}'
    assert not result['ok']


def test_R03_cleanup_rejects_a_different_cluster_fingerprint(monkeypatch):
    write_identity('learner');write_identity('reader')
    rid=ledger.begin_run('lab.review','original-cluster','https://api.old.example:6443')
    ledger.applied(ledger.intent(rid,'Project','academy-review','/apis/project.openshift.io/v1/projects/academy-review'),'original-uid')
    ledger.request_cleanup(rid)
    mutations=[]
    monkeypatch.setattr(ledger,'_delete_with_uid',lambda *args:mutations.append(args) or 'not_found')
    report=ledger.cleanup_pass(rid)
    assert not mutations, 'R03: cleanup issued a DELETE against identities on another cluster'
    assert report['state']!='clean', 'R03: absence on another cluster erased original-cluster leftovers'


def test_R04_cleanup_does_not_adopt_an_unledgered_marker_project(monkeypatch):
    monkeypatch.setattr(environment,'current',lambda:{'class':'read-only','connected':True,'fingerprint':'f','api':'https://api.example'})
    lab=labs.load()['lab.rbac']
    monkeypatch.setattr(labs,'project_state',lambda ns:{'exists':True,'owned':True,'phase':'Active'})
    monkeypatch.setattr(ledger,'uid_of',lambda *a:('found','foreign-uid'))
    monkeypatch.setattr(ledger,'note_volumes',lambda *a:[])
    mutations=[]
    monkeypatch.setattr(ledger,'_delete_with_uid',lambda *a:mutations.append(a) or 'not_found')
    labs.cleanup(lab,wait_s=0)
    assert not mutations, 'R04: a marker alone authorized deleting an unledgered project'


def test_R05_intent_recovery_cannot_adopt_an_unrelated_cluster_object(monkeypatch):
    rid=ledger.begin_run('lab.review','f')
    ledger.intent(rid,'Group','academy-auditors','/apis/user.openshift.io/v1/groups/academy-auditors',scope='cluster',identity='admin')
    # Crash BEFORE create. An existing object has the same authored name and was never ours.
    monkeypatch.setattr(ledger,'uid_of',lambda *a:('found','someone-elses-uid'))
    mutations=[]
    monkeypatch.setattr(ledger,'_delete_with_uid',lambda *a:mutations.append(a) or 'not_found')
    ledger.request_cleanup(rid);ledger.cleanup_pass(rid)
    assert not mutations, 'R05: intent recovered and deleted the UID of a foreign Group'


def test_R06_pv_reclaim_has_an_atomic_claim_uid_precondition(monkeypatch):
    # Integration note: R03's fix only lets a connected admin on the learner's cluster act, so the fixture
    # now gives both identities a kubeconfig for the same API server. The assertion is unchanged.
    write_identity('learner');write_identity('admin')
    rid=ledger.begin_run('lab.review',environment.current()['fingerprint'])  # the run belongs to the connected cluster
    with ledger._db() as db:
        db.execute("INSERT INTO volumes (pv,run_id,namespace,claim,claim_uid,phase) VALUES (?,?,?,?,?,?)",('retained-pv',rid,'academy-review','data','old-claim','released-needs-admin'))
    def read(identity,args,*a,**k):
        # Last read sees our Released PV. It is rebound before the following PATCH.
        return 'found',{'metadata':{'uid':'pv-uid','resourceVersion':'17'},'status':{'phase':'Released'},'spec':{'claimRef':{'uid':'old-claim'}}},None
    monkeypatch.setattr(kube,'read',read)
    patches=[]
    monkeypatch.setattr(kube,'oc',lambda ident,args,**kw:patches.append(args) or kube.Result(args,0,'','',0))
    monkeypatch.setattr(ledger,'cleanup_pass',lambda *a:{})
    ledger.reclaim_volumes(rid,wait_s=0)
    assert patches
    # A GET then merge PATCH is a race. JSON Patch must test UID + claim UID + phase (or CAS resourceVersion).
    patch=patches[0];body=json.loads(patch[patch.index('-p')+1])
    atomic = isinstance(body,list) and any(op.get('op')=='test' and op.get('path')=='/spec/claimRef/uid' for op in body)
    cas = isinstance(body,dict) and body.get('metadata',{}).get('resourceVersion')=='17'
    assert atomic or cas, f'R06: unguarded reclaim PATCH: {patch}'


def test_R07_transport_failure_does_not_retire_the_project_intent(monkeypatch):
    lab=labs.load()['lab.rbac'];rid=ledger.begin_run(lab.id,'f')
    monkeypatch.setattr(labs,'project_state',lambda ns:{'exists':False})
    monkeypatch.setattr(kube,'oc',lambda i,a,**k:kube.Result(a,124,'','request timed out after being accepted',0,'timeout'))
    assert labs._ensure_project(lab,lab.namespace,[],rid)
    e=ledger.effects(rid)[0]
    assert e['phase'] not in ledger.TERMINAL_OK, 'R07: timeout is not proof that the server never created the project'


def test_R08_recorder_never_persists_success_before_cleanup(monkeypatch):
    lab=SimpleNamespace(id='lab.review',title='Review',kind='lab',checks=[],commands=[],steps=[],namespaces=['academy-review'])
    monkeypatch.setattr(recorder,'cluster_meta',lambda:{})
    monkeypatch.setattr(environment,'current',lambda:{'class':'training'})  # recording needs an approved cluster
    monkeypatch.setattr(labs,'lab_hash',lambda l:'review-hash')
    cleanups=iter([{'state':'clean'},{'state':'blocked','report':{'state':'blocked','remaining':1,'effects':[],'volumes':[]}}])
    monkeypatch.setattr(labs,'cleanup',lambda *a,**k:next(cleanups))
    monkeypatch.setattr(labs,'prepare',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(recorder,'settle',lambda *a:None)
    monkeypatch.setattr(labs,'verify',lambda *a:{'verdict':'not-applicable','results':[]})
    result=recorder.record(lab,log=lambda *a:None)
    assert not result['ok']
    saved=json.loads((config.RECORDINGS_DIR/f'{lab.id}.json').read_text(encoding="utf-8"))
    assert not saved['ok'], 'R08: recording file says ok=true while cleanup is blocked'
    assert saved['problems'], 'R08: persisted problems omit the cleanup failure'


def test_recorder_touches_nothing_on_an_unapproved_cluster(monkeypatch):
    lab=SimpleNamespace(id='lab.review',title='Review',kind='lab',checks=[],commands=[],steps=[],namespaces=['academy-review'])
    monkeypatch.setattr(recorder,'cluster_meta',lambda:{})
    monkeypatch.setattr(environment,'current',lambda:{'class':'read-only'})
    monkeypatch.setattr(labs,'lab_hash',lambda l:'review-hash')
    for name in ('cleanup','adopt','prepare'):
        monkeypatch.setattr(labs,name,lambda *a,**k:(_ for _ in ()).throw(AssertionError('touched the cluster')))
    result=recorder.record(lab,log=lambda *a:None)
    assert not result['ok'] and 'not approved' in result['problems'][0]


def test_R09_capability_cache_is_not_shared_across_users(monkeypatch):
    monkeypatch.setattr(environment,'current',lambda:{'class':'training','connected':True,'fingerprint':'same-cluster','api':'https://api.example'})
    who={'user':'admin'}
    monkeypatch.setattr(kube,'whoami',lambda i:{'connected':True,'user':who['user']})
    monkeypatch.setattr(environment,'same_cluster',lambda i:True)
    monkeypatch.setattr(kube,'oc',lambda i,a,**k:kube.Result(a,0,'{}' if '--raw' in a else '','',0))
    monkeypatch.setattr(kube,'oc_json',lambda *a,**k:({'items':[]},None))
    monkeypatch.setattr(environment,'_can_i',lambda *a:who['user']=='admin')
    assert environment.probe()['access']['create-projects'] is True
    who['user']='restricted'
    assert environment.probe()['access']['create-projects'] is not True, 'R09: restricted user inherits cached admin capabilities'


def test_R17_helm_empty_values_cannot_validate_a_different_effective_render(monkeypatch,tmp_path):
    """Helm v3 reuseValues copies current.Config when parsed newVals is empty, regardless of -f presence."""
    from academy import runner
    chart=tmp_path/'chart';chart.mkdir()
    values=tmp_path/'empty.yaml';values.write_text('{}\n', encoding="utf-8")
    # Isolate the value-semantics defect from R18; this models a caller file outside /tmp.
    unlink=Path.unlink
    monkeypatch.setattr(Path,'unlink',lambda p,*a,**k:None if p==values else unlink(p,*a,**k))
    effects=[]
    safe='apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\n'
    unsafe='apiVersion: user.openshift.io/v1\nkind: Group\nmetadata:\n  name: foreign-group\n'
    def helm(identity,args,timeout=None):
        if args[:2]==['get','values']:text='privileged: true\n'
        elif args[0]=='get':text=safe  # old chart always emitted a ConfigMap, even with privileged=true
        elif args[0]=='template':
            supplied={}
            for i,arg in enumerate(args[:-1]):
                if arg=='-f':supplied.update(yaml.safe_load(open(args[i+1], encoding="utf-8")) or {})
            text=unsafe if supplied.get('privileged') else safe
        else:
            # The real upgrade of the NEW chart reuses current.Config because the supplied file parsed to {}.
            effects.append('Group/foreign-group');text='upgrade completed'
        return kube.Result(['helm',*args],0,text,'',0)
    monkeypatch.setattr(kube,'helm',helm)
    # Supply the fixed chart directory through the normal Lab interface.
    lab=SimpleNamespace(files={'empty.yaml':'{}'},namespace='academy-review')
    monkeypatch.setattr(labs,'labfiles_dir',lambda l:tmp_path)
    result=runner.execute('helm upgrade demo lab/chart -f lab/empty.yaml -n academy-review',lab=lab)
    assert result.get('refused') and not effects, f'R17: preflight accepted a render unlike the real Helm values semantics: {effects}'


def test_R18_helm_validation_does_not_delete_caller_values_files(monkeypatch,tmp_path):
    from academy import policy,runner
    (tmp_path/'chart').mkdir()
    values=tmp_path/'values.yaml';values.write_text('replicas: 3\n', encoding="utf-8")
    monkeypatch.setattr(kube,'helm',lambda identity,args,timeout=None:kube.Result(['helm',*args],0,'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\n' if args[0]=='template' else '', '',0))
    plan=policy.plan('helm upgrade demo lab/chart -f lab/values.yaml -n academy-review',labdir=str(tmp_path))
    runner._validate_helm(plan,30)
    assert values.exists(), 'R18: validation deleted a values file that the actual command still needs'


def test_R02_reader_setup_cannot_mutate_another_clusters_admin(monkeypatch):
    from academy import main
    write_identity('learner');write_identity('admin','https://api.production.example:6443')
    environment.approve('api.training.example')
    mutations=[]
    monkeypatch.setattr(kube,'oc',lambda ident,args,**kw:mutations.append((ident,args)) or kube.Result(args,0,'','',0))
    monkeypatch.setattr(kube,'refresh_reader_token',lambda steps:{'ok':True})
    try:main.reader_setup(main.ConnectIn(identity='reader',confirm='create reader'))
    except main.HTTPException:pass
    assert not mutations, 'R02: reader setup applied a Namespace and ClusterRoleBinding on the other cluster'


def test_R19_authored_cluster_delete_cannot_bypass_the_recorded_uid(monkeypatch):
    from academy import main
    lab=labs.load()['lab.groups'];obj=lab.cluster_objects[0]
    cmd=next(c for _,c in lab.all_commands() if c.cmd==obj.deleted_by)
    monkeypatch.setattr(environment,'current',lambda:{'class':'training','fingerprint':'f','api':'https://api.example'})
    rid=ledger.begin_run(lab.id,'f')
    ledger.applied(ledger.intent(rid,obj.kind,obj.name,obj.path,scope='cluster',identity='admin'),'original-uid')
    monkeypatch.setattr(ledger,'uid_of',lambda *a:('found','replacement-uid'))
    deleted=[]
    # The callback represents the ordinary authored `oc delete group <name>` (no UID precondition).
    main._run_tracked(lab,cmd,lambda:deleted.append('replacement-uid') or {'code':0})
    assert not deleted, 'R19: a lab step bypassed the ledger and deleted the replacement by name'


def test_R20_prepare_does_not_ignore_an_incompatible_preflight(monkeypatch):
    lab=labs.load()['lab.scheduling']
    monkeypatch.setattr(environment,'current',lambda:{'class':'training','connected':True,'fingerprint':'f','api':'https://api.example','crc':False})
    monkeypatch.setattr(environment,'preflight',lambda l:{'runnable':False,'blockers':[{'req':'crc','why':'not CRC'}],'unknown':[]})
    creates=[]
    monkeypatch.setattr(labs,'_ensure_project',lambda *a:creates.append(a) or None)
    monkeypatch.setattr(labs,'write_files',lambda *a:None)
    monkeypatch.setattr(labs,'apply',lambda *a,**k:[])
    result=labs.prepare(lab)
    assert not creates and not result['ok'], 'R20: prepare created projects although this lab cannot run here'


def test_R21_cleanup_cannot_claim_clean_when_project_visibility_is_unknown(monkeypatch):
    lab=labs.load()['lab.rbac']
    monkeypatch.setattr(environment,'current',lambda:{'class':'read-only','connected':True,'fingerprint':'f','api':'https://api.example'})
    monkeypatch.setattr(labs,'project_state',lambda ns:{'exists':None,'reason':'Forbidden'})
    result=labs.cleanup(lab,wait_s=0)
    assert result['state']!='clean', f'R21: unknown visibility reported as no project: {result}'


def test_R26_pvc_bindings_are_durable_before_the_claim_disappears(monkeypatch):
    """A Retain PV outlives a PVC deleted while practising; a cleanup-time-only scan is too late."""
    lab=SimpleNamespace(id='lab.review-storage',title='Review storage',namespace='academy-review',namespaces=['academy-review'],
                        setup=['apiVersion: v1\nkind: PersistentVolumeClaim\nmetadata:\n  name: data\n'],elevated_setup=[],kind='lab',files={})
    monkeypatch.setattr(environment,'current',lambda:{'class':'training','connected':True,'fingerprint':'f','api':'https://api.example'})
    # Integration note: R20's fix makes prepare enforce the preflight; this storage fixture is a minimal fake
    # lab, so the preflight is stubbed as runnable. The assertion about durable volume bindings is unchanged.
    monkeypatch.setattr(environment,'preflight',lambda l:{'runnable':True,'blockers':[],'unknown':[]})
    def project(l,ns,steps,rid):
        ledger.applied(ledger.intent(rid,'Project',ns,'/apis/project.openshift.io/v1/projects/'+ns),'project-uid')
    monkeypatch.setattr(labs,'_ensure_project',project)
    monkeypatch.setattr(labs,'write_files',lambda *a:None)
    monkeypatch.setattr(labs,'apply',lambda *a,**k:[{'code':0}])
    claim={'exists':True}
    def read(i,args,*a,**k):
        if args[:2]==['get','pvc']:
            items=[{'metadata':{'name':'data','uid':'claim-uid'},'spec':{'volumeName':'retained-pv'}}] if claim['exists'] else []
            return 'found',{'items':items},None
        return 'found',{'metadata':{'uid':'pv-uid'},'status':{'phase':'Released'},'spec':{'claimRef':{'uid':'claim-uid'},'persistentVolumeReclaimPolicy':'Retain'}},None
    monkeypatch.setattr(kube,'read',read)
    assert labs.prepare(lab)['ok']
    rid=ledger.active_run(lab.id,'f')
    # A practice command now deletes the PVC. The retained volume still exists; only the claim vanished.
    claim['exists']=False
    monkeypatch.setattr(ledger,'_delete_with_uid',lambda *a:'not_found')
    result=labs.cleanup(lab,wait_s=0)
    assert any(v['pv']=='retained-pv' for v in ledger.volumes(rid)), f'R26: lost binding, cleanup={result["state"]} while Retain PV remains'


def test_R27_logical_sqlite_corruption_blocks_destructive_recovery(monkeypatch):
    """integrity_check can RETURN errors without raising DatabaseError; ignoring its result is unsafe."""
    import sqlite3
    rid=ledger.begin_run('lab.review','f')
    ledger.applied(ledger.intent(rid,'Project','academy-review','/apis/project.openshift.io/v1/projects/academy-review'),'project-uid')
    with sqlite3.connect(ledger.DB) as db:
        db.execute('CREATE INDEX review_name_idx ON effects(name)')
        db.execute('CREATE INDEX review_kind_idx ON effects(kind)')
        roots=dict(db.execute("SELECT name,rootpage FROM sqlite_schema WHERE name IN ('review_name_idx','review_kind_idx')"))
        db.execute('PRAGMA writable_schema=ON')
        db.execute('UPDATE sqlite_schema SET rootpage=? WHERE name=?',(roots['review_kind_idx'],'review_name_idx'))
        db.execute('UPDATE sqlite_schema SET rootpage=? WHERE name=?',(roots['review_name_idx'],'review_kind_idx'))
        version=db.execute('PRAGMA schema_version').fetchone()[0]
        db.execute(f'PRAGMA schema_version={version+1}')
    with sqlite3.connect(ledger.DB) as db:
        errors=[r[0] for r in db.execute('PRAGMA integrity_check')]
    assert errors!=['ok'], 'Fixture must contain actual SQLite integrity errors'
    mutations=[]
    monkeypatch.setattr(ledger,'_delete_with_uid',lambda *a:mutations.append(a) or 'not_found')
    with pytest.raises(ledger.LedgerUnavailable):
        ledger.cleanup_pass(rid)
    assert not mutations
