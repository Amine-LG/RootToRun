import { useMemo, useState } from 'react'
import { HiCmd, Output } from '../components/Term'
import { PageHead } from '../components/PageHead'
import { CopyButton, Icon, PageSkeleton } from '../components/ui'
import { api, type CommandRef } from '../lib/data'
import { useApp, useLoad } from '../lib/app'
import { t } from '../lib/i18n'
import { searchRanked } from '../lib/search'
import { labHref, lessonHref } from '../lib/urls'

const TOOLS = ['oc', 'kubectl', 'podman'] as const
/** Which tool a command belongs to; everything else (cat, grep, helm, skopeo…) is "Linux and other". */
const toolOf = (cmd: string) => {
  const w = cmd.split(/\s+/)[0]
  return (TOOLS as readonly string[]).includes(w) ? w : 'other'
}
/** The verb of an oc / kubectl / podman command: "get", "rollout status", "adm policy", "auth can-i"… */
const COMPOUND = new Set(['adm', 'auth', 'rollout', 'set', 'policy', 'create', 'image', 'container', 'system', 'volume', 'network'])
const verbOf = (cmd: string) => {
  const w = cmd.split(/\s+/).slice(1).filter((x) => !x.startsWith('-'))
  return w[0] && COMPOUND.has(w[0]) && w[1] ? `${w[0]} ${w[1]}` : w[0] || ''
}
const PAGE = 120

export default function Commands({ query }: { query: URLSearchParams }) {
  const { lang } = useApp()
  const { data, err } = useLoad(() => api.commands(lang), [lang])
  const [q, setQ] = useState(query.get('q') || '')
  const [tool, setTool] = useState('')
  const [verb, setVerb] = useState('')
  const [open, setOpen] = useState<string | null>(query.get('q'))
  const [limit, setLimit] = useState(PAGE)

  // One entry per distinct command text, keeping every lab that uses it.
  const unique = useMemo(() => {
    const m = new Map<string, { c: CommandRef; labs: { id: string; title: string }[] }>()
    for (const c of data || []) {
      if (!c.tested) continue
      const e = m.get(c.cmd)
      if (e) {
        if (!e.labs.some((l) => l.id === c.lab)) e.labs.push({ id: c.lab, title: c.lab_title })
      } else m.set(c.cmd, { c, labs: [{ id: c.lab, title: c.lab_title }] })
    }
    return [...m.values()]
  }, [data])
  const tools = useMemo(() => {
    const count = new Map<string, number>()
    for (const u of unique) count.set(toolOf(u.c.cmd), (count.get(toolOf(u.c.cmd)) || 0) + 1)
    return [...TOOLS, 'other'].filter((x) => count.get(x)).map((x) => [x, count.get(x) as number] as const)
  }, [unique])
  const verbs = useMemo(() => {
    const count = new Map<string, number>()
    if ((TOOLS as readonly string[]).includes(tool))
      for (const u of unique) if (toolOf(u.c.cmd) === tool) count.set(verbOf(u.c.cmd), (count.get(verbOf(u.c.cmd)) || 0) + 1)
    return [...count.entries()].filter(([v]) => v).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }, [unique, tool])
  const list = searchRanked(
    unique.filter((u) => (!tool || toolOf(u.c.cmd) === tool) && (!verb || verbOf(u.c.cmd) === verb)),
    q,
    (u) => u.c.cmd,
    (u) => `${u.c.cmd} ${u.c.meaning} ${u.labs.map((l) => l.title).join(' ')}`,
  )
  const filtered = !!(q || tool || verb)
  const clear = () => { setQ(''); setTool(''); setVerb(''); setLimit(PAGE) }
  const pick = (f: () => void) => { f(); setLimit(PAGE) }

  if (err) return <div className="page">{err}</div>
  if (!data) return <div className="page"><PageSkeleton /></div>
  return (
    <div className="page commands xp">
      {/* no Report or Edit here: the commands come from the lessons, where each one can be reported or edited */}
      <PageHead eyebrow={t('nav.reference')} title={t('cmd.title')} lede={t('cmd.lede', { n: unique.length })} />
      <div className="xp-filters">
        <div className="search-in">
          <Icon name="search" size={16} />
          <input value={q} onChange={(e) => pick(() => setQ(e.target.value))} placeholder={t('cmd.search')} aria-label={t('cmd.search')} data-testid="cmd-search" />
        </div>
        <div className="chips" role="group" aria-label={t('xp.toolFilter')}>
          <button className={`chip ${!tool ? 'on' : ''}`} aria-pressed={!tool} onClick={() => pick(() => (setTool(''), setVerb('')))}>
            {t('labs.all')}
          </button>
          {tools.map(([x, n]) => (
            <button key={x} className={`chip ${tool === x ? 'on' : ''}`} aria-pressed={tool === x} onClick={() => pick(() => (setTool(tool === x ? '' : x), setVerb('')))}>
              <span className={x === 'other' ? '' : 'mono'}>{x === 'other' ? t('xp.toolOther') : x}</span> <small>{n}</small>
            </button>
          ))}
        </div>
        {verbs.length > 1 && (
          <label className="select-in">
            <span className="sr-only">{t('xp.verbFilter')}</span>
            <select value={verb} onChange={(e) => pick(() => setVerb(e.target.value))}>
              <option value="">{t('xp.anyVerb')}</option>
              {verbs.map(([v, n]) => (
                <option key={v} value={v}>
                  {tool} {v} ({n})
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <p className="xp-count cmd-count" role="status">{t('cmd.count', { n: list.length, of: unique.length })}</p>
      <div className="cmd-list">
        {list.slice(0, limit).map(({ c, labs }) => (
          <div key={c.cmd} className={`cmd-item ${open === c.cmd ? 'open' : ''}`}>
            <button className="cmd-item-h" onClick={() => setOpen(open === c.cmd ? null : c.cmd)} aria-expanded={open === c.cmd}>
              <code className="cmd-text">
                <HiCmd text={c.cmd} />
              </code>
              <span className="cmd-meaning">{c.meaning}</span>
              {c.as !== 'learner' && <span className={`who who-${c.as}`}>{c.as === 'reader' ? t('term.asReader') : c.as === 'host' ? t('term.asHost') : t('term.asAdmin')}</span>}
              <Icon name="arrow" size={14} className="chev" />
            </button>
            {open === c.cmd && (
              <div className="cmd-item-b">
                <div className="row">
                  <CopyButton text={c.cmd} />
                  <span className="muted small">{t('cmd.usedIn')}</span>
                  {labs.map((l) => (
                    <a key={l.id} href={c.kind === 'lesson' ? lessonHref(l.id) : labHref(l.id)} className="lab-chip sm">
                      {l.title}
                    </a>
                  ))}
                </div>
                {c.run && c.run !== c.cmd && (
                  <div className="muted small mono">
                    {t('play.ranAs')} {c.run}
                  </div>
                )}
                <div className="screen recorded">
                  <div className="screen-bar">
                    <span className="screen-src">{t('term.recordedOutput')}</span>
                    <span className={`exit ${c.code === 0 ? 'ok' : 'expected'}`}>{t('term.exit', { code: c.code ?? '?' })}</span>
                  </div>
                  <div className="screen-body">
                    {!c.stdout && !c.stderr ? <div className="tx-hint">{t('term.noOutput')}</div> : <Output stdout={c.stdout} stderr={c.stderr} q={q.length > 2 ? q : undefined} />}
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
      {list.length > limit && (
        <p className="xp-more">
          <button className="btn" onClick={() => setLimit(limit + PAGE)}>
            {t('xp.showMore', { n: Math.min(PAGE, list.length - limit) })}
          </button>
        </p>
      )}
      {list.length === 0 && (
        <div className="xp-empty">
          <p>{t('pal.none')}</p>
          {filtered && (
            <button className="btn sm" onClick={clear}>
              {t('xp.clearFilters')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
