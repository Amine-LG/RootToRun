import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Md, MdInline } from '../lib/md'
import { t } from '../lib/i18n'
import type { Lesson, Predict } from '../lib/data'
import { filterEntries, formatApiError, tokenFromFragment, type AuthorDraft, type AuthorEntry, type AuthorItem, type Problems, type Revision } from '../lib/authoring'
import '../authoring.css'
import '../pages.css'

function readToken() {
  let stored: string | null = null
  try { stored = sessionStorage.getItem('academy.authorToken') } catch { /* memory still works */ }
  const { token, consumed } = tokenFromFragment(location.hash, stored)
  if (consumed) {
    history.replaceState(history.state, '', location.pathname + location.search)
    try { sessionStorage.setItem('academy.authorToken', token) } catch { /* memory still works */ }
  }
  return token
}

function PreviewQuestion({ q }: { q: Predict }) {
  const [choice, setChoice] = useState<number | null>(null)
  return <fieldset className="author-question">
    <legend><MdInline text={q.prompt} /></legend>
    {q.choices.map((label, i) => <label key={i}>
      <input type="radio" name={`author-${q.id}`} checked={choice === i} onChange={() => setChoice(i)} />
      <span><MdInline text={label} /></span>
    </label>)}
    {choice !== null && <div role="status"><strong>{choice === q.answer ? t('author.correct') : t('author.incorrect')}</strong>{q.feedback?.[choice] && <Md text={q.feedback[choice]} />}<Md text={q.explain} /></div>}
  </fieldset>
}

/** A lesson written as a teaching flow, step by step, as an author needs to check it: every step visible, accepted
 * commands and hints of practice steps listed, recorded commands named (the output appears once recorded). */
function FlowPreview({ lesson }: { lesson: Lesson }) {
  const asked = new Map(lesson.predict.map((q) => [q.after || '', q]))
  return <ol className="author-flow">
    {(lesson.flow || []).map((st) => <li key={st.id} className={`author-step step-${st.kind}`}>
      <span className="author-step-kind">{st.kind} · {st.id}</span>
      {st.kind === 'teach' && <>{st.title && <h3>{st.title}</h3>}<Md text={st.body} /></>}
      {st.kind === 'show' && <>{st.title && <h3>{st.title}</h3>}{st.body && <Md text={st.body} />}
        {st.run && <pre className="code"><code>{`$ ${st.run}`}</code></pre>}
        {st.code != null && <pre className="code"><code>{st.code}</code></pre>}
        {st.notice && <Md text={st.notice} />}</>}
      {st.kind === 'try' && <>{st.title && <h3>{st.title}</h3>}<Md text={st.body} />
        <p><strong>{t('author.accepts')}</strong> {st.accept.map((a) => <code key={a}>{a}</code>).reduce<ReactNode[]>((acc, x, i) => (i ? [...acc, ', ', x] : [x]), [])}</p>
        <ul>{st.hints.map((h) => <li key={h.match}><code>{h.match}</code>: <MdInline text={h.say} /></li>)}</ul>
        {st.then && <Md text={st.then} />}</>}
      {st.kind === 'ask' && asked.get(st.id) && <>{st.guess && <p><em>{t('author.guess')}</em></p>}<PreviewQuestion q={asked.get(st.id)!} /></>}
      {st.kind === 'order' && <><Md text={st.prompt} /><ol>{st.items.map((it) => <li key={it}><MdInline text={it} /></li>)}</ol><Md text={st.why} /></>}
      {st.kind === 'reflect' && <><Md text={st.prompt} /><details><summary>{t('author.modelAnswer')}</summary><Md text={st.model} /></details></>}
      {st.kind === 'explore' && <><p><code>{st.sim || st.diagram}</code></p>{st.body && <Md text={st.body} />}</>}
    </li>)}
  </ol>
}

function LessonPreview({ lesson }: { lesson: Lesson }) {
  if (lesson.flow?.length) return <article><h2>{lesson.title}</h2><p>{lesson.subtitle}</p><Md text={lesson.objective} /><FlowPreview lesson={lesson} />
    {!!lesson.review.length && <h3>{t('author.review')}</h3>}
    {lesson.review.map((card, i) => <details key={i}><summary><MdInline text={card.q} /></summary><Md text={card.a} /></details>)}
  </article>
  const questions = (section: string, role: 'predict' | 'check') => lesson.predict.filter(q =>
    (q.role || 'check') === role && (role === 'predict' ? q.answered_by === section : (q.after || lesson.sections.filter(s => !s.depth).slice(-1)[0]?.id) === section),
  ).map(q => <PreviewQuestion q={q} key={q.id} />)
  return <article>
    <h2>{lesson.title}</h2><p>{lesson.subtitle}</p><Md text={lesson.objective} />
    {questions('start', 'check')}
    {lesson.sections.map(section => <section key={section.id}>
      {questions(section.id, 'predict')}<h3>{section.title}</h3><Md text={section.body} />{questions(section.id, 'check')}
    </section>)}
    {lesson.explain.map((prompt, i) => <section key={i}><h3>{prompt.prompt}</h3><p>{prompt.audience}</p><ul>{prompt.rubric.map((line, j) => <li key={j}>{line}</li>)}</ul><details><summary>{t('author.modelAnswer')}</summary><Md text={prompt.model} /></details></section>)}
    {!!lesson.review.length && <h3>{t('author.review')}</h3>}
    {lesson.review.map((card, i) => <details key={i}><summary><MdInline text={card.q} /></summary><Md text={card.a} /></details>)}
    {lesson.limits && <Md text={lesson.limits} />}{lesson.enterprise && <Md text={lesson.enterprise} />}
    <ul>{lesson.references.map(ref => <li key={ref.url}><Md text={`[${ref.title}](${ref.url})`} /></li>)}</ul>
  </article>
}

export default function Author() {
  const [token] = useState(readToken)
  const [entries, setEntries] = useState<AuthorEntry[]>([])
  const [drafts, setDrafts] = useState<AuthorDraft[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<AuthorItem | null>(null)
  const [source, setSource] = useState('')
  const [problems, setProblems] = useState<Problems | null>(null)
  const [preview, setPreview] = useState<Lesson | null>(null)
  const [tab, setTab] = useState<'problems' | 'preview'>('problems')
  const [revisions, setRevisions] = useState<Revision[] | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedSource, setSavedSource] = useState('')
  const [creating, setCreating] = useState(false)
  const [createKind, setCreateKind] = useState<'lesson' | 'diagnostic'>('lesson')
  const [createFile, setCreateFile] = useState('en/lessons/')
  const loadNumber = useRef(0)
  const editor = useRef<HTMLTextAreaElement>(null)
  const lines = useRef<HTMLPreElement>(null)
  const dirty = (selected !== null || creating) && source !== savedSource

  async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const response = await fetch(`/api/author/${path}`, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'X-Academy': '1' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(formatApiError(data.detail))
    return data as T
  }

  async function refresh() {
    const [items, saved] = await Promise.all([api<AuthorEntry[]>('index'), api<AuthorDraft[]>('draft')])
    setEntries(items); setDrafts(saved)
  }

  useEffect(() => {
    if (token) void refresh().catch(e => setError(String(e.message)))
  }, [token])

  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', leave)
    return () => window.removeEventListener('beforeunload', leave)
  }, [dirty])

  useEffect(() => {
    setProblems(null); setPreview(null)
    if (!selected) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const body = { kind: selected.kind, id: selected.id, yaml: source }
        const result = await api<Problems>('validate', body, controller.signal)
        if (controller.signal.aborted) return
        setProblems(result)
        if (result.ok && selected.kind === 'lesson') {
          const lesson = await api<Lesson>('preview', body, controller.signal)
          if (!controller.signal.aborted) setPreview(lesson)
        }
      } catch (e) {
        if (!controller.signal.aborted) setProblems({ ok: false, errors: [String((e as Error).message)], warnings: [] })
      }
    }, 450)
    return () => { clearTimeout(timer); controller.abort() }
  }, [selected, source, token])

  const body = () => ({ kind: selected!.kind, id: selected!.id, yaml: source, base_hash: selected!.hash })
  const canLeave = () => !dirty || window.confirm(t('author.unsaved'))

  function adopt(item: AuthorItem, yaml = item.yaml) {
    setSelected(item); setSource(yaml); setSavedSource(yaml); setProblems(null); setPreview(null)
    setRevisions(null); setCreating(false); setError(''); setMessage('')
  }

  async function open(entry: AuthorEntry, draft?: AuthorDraft) {
    if (!canLeave()) return
    const number = ++loadNumber.current
    setBusy(true); setError('')
    try {
      const item = await api<AuthorItem>(`item/${entry.kind}/${encodeURIComponent(entry.id)}`)
      if (number === loadNumber.current) {
        adopt(draft ? { ...item, hash: draft.base_hash } : item, draft?.yaml ?? item.yaml)
        editor.current?.focus()
      }
    } catch (e) { setError(String((e as Error).message)) }
    finally { if (number === loadNumber.current) setBusy(false) }
  }

  async function action(task: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await task() } catch (e) { setError(String((e as Error).message)) }
    finally { setBusy(false) }
  }

  async function publish() {
    if (!selected || !problems?.ok) return
    if (!window.confirm([t('author.confirmPublish'), ...problems.warnings].join('\n\n'))) return
    await action(async () => {
      const item = await api<AuthorItem>('publish', body())
      adopt(item); setMessage(t('author.published')); await refresh()
    })
  }

  async function restore(revision: Revision) {
    if (!selected || !window.confirm(t('author.confirmRestore'))) return
    await action(async () => {
      const item = await api<AuthorItem>('rollback', { kind: selected.kind, id: selected.id, revision: revision.revision, base_hash: selected.hash })
      adopt(item); setMessage(t('author.restored')); await refresh()
    })
  }

  if (!token) return <div className="page pg pg-author"><header className="pg-head"><div className="eyebrow">{t('author.eyebrow')}</div><h1>{t('author.title')}</h1><p className="pg-purpose">{t('author.needToken')}</p></header></div>

  return <div className="page author-page pg pg-author">
    <header className="pg-head"><div className="eyebrow">{t('author.eyebrow')}</div><h1>{t('author.title')}</h1><p className="pg-purpose">{t('author.intro')}</p></header>
    <p className="au-status" role="status" aria-live="polite">{busy ? t('author.working') : message}</p>
    {error && <p role="alert" className="author-error">{error}</p>}
    <div className="author-layout">
      <aside className="author-list" aria-label={t('author.items')}>
        <label htmlFor="author-search">{t('author.search')}</label>
        <input id="author-search" value={query} onChange={e => setQuery(e.target.value)} type="search" />
        <button className="btn" disabled={busy} onClick={() => { if (canLeave()) { setCreating(true); setSelected(null); setSource(''); setSavedSource(''); setRevisions(null) } }}>{t('author.new')}</button>
        <ul>{filterEntries(entries, query).map(entry => <li key={`${entry.kind}/${entry.id}`}>
          <button disabled={busy} className={selected?.kind === entry.kind && selected.id === entry.id ? 'selected' : ''} aria-current={selected?.kind === entry.kind && selected.id === entry.id ? 'true' : undefined} onClick={() => void open(entry)}>
            <strong>{entry.title}</strong><small>{entry.kind} · {entry.id}</small>
          </button>
        </li>)}</ul>
        <h2>{t('author.drafts')}</h2>
        {!drafts.length && <p>{t('author.noDrafts')}</p>}
        <ul>{drafts.map(draft => <li key={`${draft.kind}/${draft.id}`}><button disabled={busy} onClick={() => void open({ ...draft, title: draft.id }, draft)}>{draft.id}<small>{draft.saved_at}</small></button></li>)}</ul>
      </aside>
      <section className="author-editor" aria-label={t('author.editor')}>
        {creating && <div className="author-create">
          <h2>{t('author.new')}</h2><p>{t('author.createHelp')}</p>
          <label htmlFor="author-kind">{t('author.kind')}</label>
          <select id="author-kind" value={createKind} disabled={busy} onChange={e => { const kind = e.target.value as 'lesson' | 'diagnostic'; setCreateKind(kind); setCreateFile(`en/${kind === 'lesson' ? 'lessons' : 'diagnostics'}/`) }}>
            <option value="lesson">{t('author.lesson')}</option><option value="diagnostic">{t('author.diagnostic')}</option>
          </select>
          <label htmlFor="author-file">{t('author.file')}</label><input id="author-file" value={createFile} disabled={busy} onChange={e => setCreateFile(e.target.value)} />
        </div>}
        {selected && <><h2>{selected.title}</h2><p className="mono author-path">{selected.file}</p></>}
        {selected || creating ? <>
          <label htmlFor="author-yaml">{t('author.yaml')}</label>
          <div className="author-source">
            <pre ref={lines} aria-hidden="true">{source.split('\n').map((_, i) => i + 1).join('\n')}</pre>
            <textarea ref={editor} id="author-yaml" value={source} disabled={busy} spellCheck={false} wrap="off" onScroll={e => { if (lines.current) lines.current.scrollTop = e.currentTarget.scrollTop }} onChange={e => { setSource(e.target.value); setProblems(null); setPreview(null); setMessage('') }} />
          </div>
          <div className="author-actions">
            {creating ? <button className="btn primary" disabled={busy || !source.trim()} onClick={() => { if (window.confirm(t('author.confirmCreate'))) void action(async () => { const item = await api<AuthorItem>('create', { kind: createKind, file: createFile, yaml: source }); adopt(item); setMessage(t('author.published')); await refresh() }) }}>{t('author.create')}</button> : <>
              <button className="btn" disabled={busy} onClick={() => void action(async () => { await api('draft', body()); setSavedSource(source); setMessage(t('author.draftSaved')); await refresh() })}>{t('author.saveDraft')}</button>
              <button className="btn primary" disabled={busy || !problems?.ok} onClick={() => void publish()}>{t('author.publish')}</button>
              <button className="btn" disabled={busy} onClick={() => void action(async () => setRevisions(await api<Revision[]>(`revisions/${selected!.kind}/${encodeURIComponent(selected!.id)}`)))}>{t('author.history')}</button>
              <button className="btn" disabled={busy} onClick={() => void open(selected!)}>{t('author.reload')}</button>
            </>}
          </div>
          <p>{t('author.gitDiff')} <code>git diff -- content/en/</code></p>
          {revisions && <section aria-label={t('author.history')}><h3>{t('author.history')}</h3>{!revisions.length && <p>{t('author.noRevisions')}</p>}{revisions.map(revision => <details key={revision.revision}><summary>{revision.revision}</summary><pre>{revision.yaml}</pre><button className="btn" disabled={busy} onClick={() => void restore(revision)}>{t('author.restore')}</button></details>)}</section>}
        </> : <p>{t('author.choose')}</p>}
      </section>
      <section className="author-inspect" aria-label={t('author.inspect')}>
        <div className="author-tabs" role="tablist" aria-label={t('author.inspect')}>
          {(['problems', 'preview'] as const).map(name => <button key={name} id={`author-tab-${name}`} role="tab" aria-selected={tab === name} aria-controls={`author-panel-${name}`} tabIndex={tab === name ? 0 : -1} onClick={() => setTab(name)} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) { e.preventDefault(); const next = e.key === 'Home' ? 'problems' : e.key === 'End' ? 'preview' : tab === 'problems' ? 'preview' : 'problems'; setTab(next); document.getElementById(`author-tab-${next}`)?.focus() } }}>{t(`author.${name}`)}</button>)}
        </div>
        <div role="tabpanel" id="author-panel-problems" aria-labelledby="author-tab-problems" tabIndex={0} hidden={tab !== 'problems'}>
          <div aria-live="polite">
            {!selected ? <p className="muted">{t('author.inspectIdle')}</p> : !problems ? <p>{t('author.validating')}</p> : <>
              <p>{problems.ok ? t('author.valid') : t('author.invalid')}</p>
              <ul className="author-error">{problems.errors.map((problem, i) => <li key={i}>{problem}</li>)}</ul>
              <ul className="author-warning">{problems.warnings.map((problem, i) => <li key={i}>{problem}</li>)}</ul>
            </>}
          </div>
        </div>
        <div role="tabpanel" id="author-panel-preview" aria-labelledby="author-tab-preview" tabIndex={0} hidden={tab !== 'preview'}>
          {preview ? <LessonPreview key={JSON.stringify(preview)} lesson={preview} /> : <p>{selected?.kind === 'lesson' ? t('author.previewWait') : t('author.previewLessons')}</p>}
        </div>
      </section>
    </div>
  </div>
}
