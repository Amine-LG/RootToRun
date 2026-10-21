"""Adversarial learner journeys; no cluster requests. Fake live replies stay inside the practice fixture."""
import json
import re
from playwright.sync_api import expect
from addresses import lab_url, lesson_url


def progress(**patch):
    p={'v':2,'lessons':{},'predictions':{},'guesses':{},'explains':{},'labs':{},'cards':{},'confidence':{},'days':[],'cmds':{},'xp':0}
    p.update(patch);return p


def seed(page,p):
    page.add_init_script('localStorage.setItem("osa.progress.v2",'+json.dumps(json.dumps(p))+')')


def open_(page,site,path):
    page.goto(site.rstrip('/')+path)
    page.wait_for_selector('main .page:not(:has(.sk-page))')


def mock_live(page, verdict='failed', execution=None):
    def reply(route,body):route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
    page.route('**/api/meta',lambda r:reply(r,{'mode':'cluster','langs':['en'],'default_lang':'en'}))
    page.route('**/api/status*',lambda r:reply(r,{'mode':'cluster','oc':True,'crc':{},'identities':{'learner':{'connected':True,'user':'fake'},'reader':{'connected':False},'admin':{'connected':False}}}))
    page.route('**/api/environment*',lambda r:reply(r,{'env':{'class':'training','reason':''},'identities':{}}))
    page.route('**/api/labs/*/state*',lambda r:reply(r,{'project':{'exists':True,'owned':True},'items':[],'events':[]}))
    page.route('**/api/labs/*/preflight*',lambda r:reply(r,{'class':'training','runnable':True,'requirements':[],'blockers':[],'notes':[]}))
    page.route('**/api/labs/*/verify*',lambda r:reply(r,{'verdict':verdict,'at':99999,'results':[]}))
    if execution:page.route('**/api/labs/*/exec*',lambda r:reply(r,execution(r) if callable(execution) else execution))


def test_R10_skipped_reading_is_not_reported_as_read(page,static_site):
    open_(page,static_site,lesson_url("d.routes-tls"))
    page.get_by_test_id('test-out').click()
    from test_learning_model import answer_all_right
    answer_all_right(page,static_site,'d.routes-tls')  # choices are shown in a shuffled order
    page.get_by_test_id('skip-reading').click()
    p=page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2'))")
    assert p['lessons']['d.routes-tls']['skipped'] and not p['lessons']['d.routes-tls'].get('done')
    open_(page,static_site,'/map?concept=net.routes')
    expect(page.locator('.graph-inspector')).to_contain_text(re.compile(r'Reading: 0/')) # R10


def test_R11_failed_lab_verdict_overrides_an_older_success(page,practice_server):
    seed(page,progress(labs={'lab.rbac':{'verified':1000,'verdict':'verified','verdictAt':1000}}))
    mock_live(page,'failed')
    open_(page,practice_server,lab_url("lab.rbac"))
    page.get_by_test_id('verify').click()
    expect(page.locator('.env .checks')).to_contain_text('No check passes')
    expect(page.locator('.lab-h')).to_contain_text('Last live check failed') # R11


def test_R11_repeated_success_is_not_reported_as_failure(page,practice_server):
    seed(page,progress(labs={'inc.service-selector-503':{'verified':1000,'verdict':'verified','verdictAt':1000}}))
    mock_live(page,'verified')
    open_(page,practice_server,lab_url("inc.service-selector-503"))
    page.get_by_test_id('verify').click()
    expect(page.locator('.env .checks')).to_contain_text('Verified')
    expect(page.locator('.lab-h')).to_contain_text('Verified on a cluster') # R11


def test_R12_incident_resume_keeps_the_return_activity(page,static_site):
    open_(page,static_site,lab_url("inc.service-selector-503") + '?from=%2Flesson%2Fd.services-dns%3Fa%3Dpractise')
    page.get_by_test_id('start-investigating').click()
    here=page.url
    open_(page,static_site,'/')
    page.get_by_role('link',name=re.compile('Continue the investigation')).click()
    page.wait_for_selector('.lab.player')
    assert 'stage=investigate' in page.url and 'from=' in page.url, f'R12: resume dropped context: {here} -> {page.url}'


def test_R13_check_is_immediately_after_its_teaching_section(page,static_site):
    open_(page,static_site,lesson_url("h.observability"))
    page.wait_for_selector('[data-testid=flow-step]')
    kinds=page.locator('[data-testid=flow-step]').evaluate_all('els => els.map(e => e.dataset.kind)')
    k=kinds.index('check')
    assert kinds[k-1] in ('learn','check'), f'R13: activities before Check: {kinds}'


def test_R14_revealing_an_incident_updates_the_stage_url(page,static_site):
    open_(page,static_site,lab_url("inc.service-selector-503") + '?stage=diagnose')
    page.locator('textarea.diag').fill('The Service selector does not match the Pod labels.')
    page.get_by_test_id('reveal').click()
    expect(page.locator('.debrief-full')).to_be_visible()
    assert 'stage=debrief' in page.url, f'R14: visible debrief but stale URL: {page.url}'
    page.reload()
    expect(page.locator('.debrief-full')).to_be_visible()


def test_R15_hint_spacing_survives_a_stage_switch(page,static_site):
    open_(page,static_site,lab_url("inc.service-selector-503") + '?stage=investigate')
    page.get_by_test_id('hint').click()
    expect(page.locator('.hint')).to_have_count(1)
    expect(page.get_by_test_id('hint')).to_be_disabled()
    page.get_by_role('button',name='I have a theory',exact=True).click()
    expect(page.get_by_test_id('hint')).to_be_disabled() # R15: still within the same 15-second gap


def test_R16_transport_error_cannot_complete_an_expect_any_step(page,practice_server):
    # The authored expect:any logs example allows ordinary CLI failure, not a missing/timed-out execution.
    mock_live(page,execution=lambda r:{'code':124,'status':'timeout','stdout':'','stderr':'Execution timed out'} if r.request.post_data_json['index']==0 else {'code':0,'stdout':'expected logs','stderr':''})
    open_(page,practice_server,lab_url("lab.troubleshooting-tools") + '?step=logs')
    step=page.locator('.lab-step')
    if step.get_by_test_id('skip-guess').count():step.get_by_test_id('skip-guess').click()
    for block in step.locator('.cmdblock').all():
        if block.get_by_test_id('run-live').count():
            block.get_by_test_id('run-live').click()
            if block.get_by_test_id('confirm-run').count():block.get_by_test_id('confirm-run').click()
    page.wait_for_timeout(200)
    p=page.evaluate("JSON.parse(localStorage.getItem('osa.progress.v2')||'{}')")
    results=p.get('labs',{}).get('lab.troubleshooting-tools',{}).get('stepResults',{})
    assert results and all(not r['matched'] for r in results.values()), f'R16: transport timeout counted as matched: {results}'


def test_R10_live_verification_is_not_a_recording_worked_through(page,static_site):
    seed(page,progress(labs={'lab.rbac':{'verified':1000,'verdict':'verified','verdictAt':1000}}))
    open_(page,static_site,'/map?concept=sec.rbac')
    # a lab verified live is completed practice and verified, never "recordings worked through" (lib/standing.ts)
    expect(page.locator('.graph-inspector')).to_contain_text('Verified on a cluster: 1')
    expect(page.locator('.graph-inspector')).to_contain_text('Practice completed: 1/')
    expect(page.locator('.graph-inspector')).not_to_contain_text('Recordings') # R10
