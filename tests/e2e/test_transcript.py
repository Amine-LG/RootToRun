"""Real recorded CLI tables and exact retained streams, exercised through the built static UI."""
import json
from pathlib import Path
import pytest
from playwright.sync_api import expect

ROOT=Path(__file__).resolve().parents[2]


INJECTS_SCRIPTS = True  # axe-core is added with a <script> tag (see conftest.py)

@pytest.fixture(scope='module')
def result_harness(tmp_path_factory):
    """Build a temporary consumer of the public exports; no application test hooks or live API."""
    import functools
    import http.server
    import socket
    import subprocess
    import threading
    root=tmp_path_factory.mktemp('transcript-contract')
    try:
        (root/'node_modules').symlink_to(ROOT/'frontend/node_modules',target_is_directory=True)
    except OSError:  # Windows without Developer Mode may not create links: a directory junction works there
        import _winapi
        _winapi.CreateJunction(str(ROOT/'frontend/node_modules'),str(root/'node_modules'))
    (root/'index.html').write_text('<div id="root"></div><script type="module" src="/harness.tsx"></script>', encoding="utf-8")
    source=f"""import React from 'react';
import {{createRoot}} from 'react-dom/client';
import {{AppProvider}} from '{ROOT.as_posix()}/frontend/src/lib/app';
import {{CommandBlock,Stream}} from '{ROOT.as_posix()}/frontend/src/components/Term';
import '{ROOT.as_posix()}/frontend/src/styles.css';
const cmd={{cmd:'oc get example -n academy-audit',as:'learner',expect:'fail',meaning:'Expected failure example',skip:'',run:null,stdin:null,timeout:10}};
const entry={{cmd:cmd.cmd,step:'audit',as:'learner',expect:'fail',code:7,stdout:'  retained stdout \\n\\n',stderr:'retained stderr\\r\\n',ok:true,run:null}};
(window as any).__results=[];(window as any).__legacy=[];
createRoot(document.getElementById('root')!).render(<AppProvider><CommandBlock c={{cmd as any}} entry={{entry}} onResult={{r=>(window as any).__results.push(r)}} onRan={{(ok,live)=>(window as any).__legacy.push({{ok,live}})}}/><div className="screen transcript wrap"><Stream text={{'x'.repeat(65001)+'\\n   '}} truncation={{{{omitted:12000,position:'start'}}}}/></div></AppProvider>);
"""
    (root/'harness.tsx').write_text(source, encoding="utf-8")
    result=subprocess.run(['node',str(ROOT/'frontend/node_modules/vite/bin/vite.js'),'build',str(root),'--config',str(ROOT/'frontend/vite.config.ts'),'--outDir',str(root/'dist')],cwd=ROOT/'frontend',capture_output=True,text=True, encoding="utf-8")
    assert result.returncode == 0,result.stderr
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(root/'dist'))
    handler.log_message=lambda *args:None
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{port}/'
    server.shutdown()


def recorded_wide():
    rows=[]
    for path in sorted((ROOT/'content/recordings').glob('*.json')):
        for e in json.loads(path.read_text(encoding="utf-8")).get('entries',[]):
            if ' -o wide' in e.get('cmd','') and e.get('code') == 0 and not e.get('skipped') and e.get('stdout','').count('\n') >= 2:
                rows.append((path,e))
    return rows


def prepare(page, site, outputs):
    page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text}}})")
    def corpus(route):
        response=route.fetch()
        original=response.json()
        original += [{'cmd':cmd,'stdout':out,'stderr':err,'code':0,'tested':True,'run':None,'lab':'audit','lab_title':'Retained-output test','kind':'lab','as':'learner','meaning':'Audit fixture','skip':''} for cmd,out,err in outputs]
        route.fulfill(response=response, json=original)
    page.route('**/data/en/commands.json',corpus)
    page.goto(site.rstrip('/') + '/terminal')
    page.wait_for_selector('[data-testid=term-input]')


def submit(page, cmd):
    inp=page.get_by_test_id('term-input');inp.fill(cmd);inp.press('Enter')


def assert_wrap(page):
    overflow=page.evaluate("[...document.querySelectorAll('.tx-body,.screen-body,.transcript-stream,.tx-table-wrap')].filter(e=>e.getClientRects().length).map(e=>({cls:e.className,n:e.scrollWidth-e.clientWidth})).filter(x=>x.n>1)")
    assert not overflow,overflow
    assert page.evaluate('document.documentElement.scrollWidth') <= page.viewport_size['width'] + 1
    nested=page.evaluate("[...document.querySelectorAll('.tx-body *')].filter(e=>/auto|scroll/.test(getComputedStyle(e).overflowY)&&e.scrollHeight>e.clientHeight+1).length")
    assert nested == 0


@pytest.mark.parametrize('width', [390,820,1440])
def test_real_recorded_wide_tables(browser, static_site, width):
    ctx=browser.new_context(viewport={'width':width,'height':900}, reduced_motion='reduce')
    page=ctx.new_page()
    # Both an actual wide pod table and a RoleBinding with entirely empty columns.
    candidates=recorded_wide()
    wide=next(e for _,e in candidates if 'NOMINATED NODE' in e['stdout'])
    empty=next(e for _,e in candidates if 'SERVICEACCOUNTS' in e['stdout'] and 'reporter-view' in e['stdout'])
    commands=[('oc get audit-wide -n academy-audit',wide['stdout'],''),('oc get audit-empty -n academy-audit',empty['stdout'],'')]
    prepare(page,static_site,commands)
    for cmd,_,_ in commands:submit(page,cmd)
    page.wait_for_timeout(300)
    assert page.locator('.tx-nomatch').count() == 0,'Test must actually match recorded output'
    if width == 390:
        expect(page.locator('.transcript-row-cards').first).to_be_visible()
        assert page.locator('.transcript-row-cards dt').filter(has_text='GROUPS').count() == 0
        assert page.locator('.transcript-row-cards dt').filter(has_text='USERS').count() == 0
    # The alternative is honest plain text, still wrapping, rather than an ineffective wrap toggle.
    page.get_by_role('button',name='Format tables',exact=True).click()
    expect(page.locator('.transcript-row-cards:visible,.tx-table:visible')).to_have_count(0)
    assert_wrap(page)
    page.get_by_role('button',name='Format tables',exact=True).click()
    short=page.locator('.tx-short:visible').all()
    assert short
    for cell in short:
        assert cell.evaluate("e=>getComputedStyle(e).whiteSpace") == 'nowrap'
    assert_wrap(page)
    ctx.close()


@pytest.mark.parametrize('width', [390,1440])
def test_yaml_json_stack_and_exact_raw_copy(browser, static_site, width):
    ctx=browser.new_context(viewport={'width':width,'height':900}, reduced_motion='reduce')
    page=ctx.new_page()
    stdout='apiVersion: v1\nkind: ConfigMap\ndata:\n  json: '+json.dumps({'message':'path/with/a-very-long-name/'*20})+'  \n\n'
    stderr='Traceback (most recent call last):\r\n  File "/a/long/path/example.py", line 17, in reconcile\r\nValueError: '+('long exception detail '*50)+'\r\n'
    cmd='oc get audit-raw -n academy-audit'
    prepare(page,static_site,[(cmd,stdout,stderr)])
    submit(page,cmd)
    entry=page.locator('.tx-entry').last
    entry.get_by_role('button',name='Copy stdout',exact=True).click()
    assert page.evaluate('window.__copied') == stdout
    entry.get_by_role('button',name='Copy stderr',exact=True).click()
    assert page.evaluate('window.__copied') == stderr
    assert_wrap(page)
    ctx.close()


def test_long_multiple_tables_share_preview_budget(page, static_site):
    out='\n\n'.join('NAME  AGE\n'+'\n'.join(f'web   {i}m' for i in range(140)) for _ in range(3))+'\n'
    prepare(page,static_site,[('oc get audit-long -n academy-audit',out,'')])
    submit(page,'oc get audit-long -n academy-audit')
    expect(page.locator('.transcript-preview-note')).to_contain_text('Preview: 200')
    before=page.locator('.tx-table tbody tr').count()
    assert before < 210
    page.get_by_role('button',name='Copy stdout',exact=True).click()
    assert page.evaluate('window.__copied') == out
    page.get_by_role('button',name='Show ',exact=False).last.click()
    expect(page.locator('.transcript-preview-note')).to_contain_text('retained lines shown')
    assert page.locator('.tx-table tbody tr').count() == 420
    assert_wrap(page)


def test_public_result_callback_and_long_truncated_stream(page, result_harness):
    page.set_viewport_size({'width':390,'height':844})
    page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text}}})")
    page.goto(result_harness)
    page.get_by_test_id('replay').click()
    assert page.evaluate('window.__results') == [{'source':'recording','expected':'fail','status':'fail','matched':True}]
    assert page.evaluate('window.__legacy') == [{'ok':True,'live':False}]
    page.locator('.cmdblock').get_by_role('button',name='Copy stdout',exact=True).click()
    assert page.evaluate('window.__copied') == '  retained stdout \n\n'
    expect(page.locator('.transcript-stream').last).to_contain_text('12000 characters omitted at the start')
    page.locator('.transcript-stream').last.get_by_role('button',name='Copy stdout',exact=True).click()
    assert page.evaluate('window.__copied') == 'x'*65001+'\n   '
    assert_wrap(page)


def test_multiple_ports_wrap_between_atomic_values(page, static_site):
    page.set_viewport_size({'width':390,'height':844})
    ports='80/TCP,443/TCP,8080/TCP,9090/TCP'
    out=f'{"NAME":6}{"PORTS":60}AGE\n{"web":6}{ports:60}3m\n'
    cmd='oc get audit-ports -n academy-audit'
    prepare(page,static_site,[(cmd,out,'')]);submit(page,cmd)
    tokens=page.locator('.transcript-row-cards:visible .tx-token')
    expect(tokens).to_have_count(4)
    for i,port in enumerate(ports.split(',')):
        assert tokens.nth(i).inner_text() == port
        assert tokens.nth(i).evaluate('e=>getComputedStyle(e).whiteSpace') == 'nowrap'
    assert_wrap(page)


@pytest.mark.parametrize('theme',['light','dark'])
def test_reduced_motion_scroll_and_suggestions_accessibility(browser, static_site, theme):
    ctx=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
    ctx.add_init_script(f"localStorage.setItem('osa.theme','{theme}')")
    ctx.add_init_script("window.__scrolls=[];const scroll=HTMLElement.prototype.scrollTo;HTMLElement.prototype.scrollTo=function(...args){if(args[0]?.behavior)window.__scrolls.push(args[0].behavior);return scroll.apply(this,args)}")
    page=ctx.new_page();cmd='oc get audit-suggestions -n academy-audit'
    prepare(page,static_site,[(cmd,'NAME  READY  STATUS   AGE\nweb   1/1    Running  3m\n','')])
    submit(page,cmd)
    assert page.evaluate('window.__scrolls.length') > 0
    assert page.evaluate("window.__scrolls.every(x=>x==='auto')")
    page.get_by_test_id('term-input').fill('oc get audit')
    expect(page.locator('.tx-suggest')).to_be_visible()
    page.add_script_tag(path=str(ROOT/'frontend/node_modules/axe-core/axe.min.js'))
    violations=page.evaluate("async()=> (await axe.run(document)).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))")
    assert not violations,violations
    assert_wrap(page);ctx.close()


@pytest.mark.parametrize('theme',['light','dark'])
def test_command_reference_retained_copy_and_completeness_note(browser, static_site, theme):
    from urllib.parse import quote
    ctx=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
    ctx.add_init_script(f"localStorage.setItem('osa.theme','{theme}')")
    ctx.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text}}})")
    page=ctx.new_page()
    corpus=page.request.get(static_site.rstrip('/')+'/data/en/commands.json').json()
    example=next(c for c in corpus if c['tested'] and c['code']==0 and c['as']=='learner' and c['stdout'].startswith('NAME'))
    page.goto(static_site.rstrip('/')+'/commands?q='+quote(example['cmd']))
    expect(page.locator('.transcript-reference')).to_contain_text('may have been shortened')
    page.get_by_role('button',name='Copy stdout',exact=True).click()
    assert page.evaluate('window.__copied') == example['stdout']
    assert_wrap(page)
    page.add_script_tag(path=str(ROOT/'frontend/node_modules/axe-core/axe.min.js'))
    violations=page.evaluate("async()=> (await axe.run(document)).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))")
    assert not violations,violations
    ctx.close()
