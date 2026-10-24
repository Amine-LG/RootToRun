import { useMemo, useState } from 'react'
import { PageHead } from '../components/PageHead'
import { Icon, LabStatusPill, LevelDots } from '../components/ui'
import type { LabSummary } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { search } from '../lib/search'
import { labStatus, useProgress } from '../lib/progress'
import { activityDone } from '../lib/standing'
import { labHref, trackHref } from '../lib/urls'
import '../practice.css'

function useTrackOf() {
  const { cur } = useApp()
  return useMemo(() => {
    const m = new Map<string, { track: string; trackTitle: string; moduleTitle: string; order: number }>()
    let order = 0
    for (const tr of cur?.tracks || [])
      for (const mid of tr.modules) m.set(mid, { track: tr.id, trackTitle: tr.title, moduleTitle: cur?.modules.find((x) => x.id === mid)?.title || mid, order: order++ })
    return m
  }, [cur])
}

/** The header of a list page: what this is, and how far the learner has got (a number and a bar, not colour alone). */
function ListHead({ title, lede, done, total, what }: { title: string; lede: string; done: number; total: number; what: string }) {
  return (
    <PageHead
      eyebrow={t('nav.practice')}
      title={title}
      lede={lede}
      aside={
        <span className="score">
          <strong>
            {done}/{total}
          </strong>
          <small>{what}</small>
          <span className="bar" role="progressbar" aria-label={what} aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-valuetext={`${done}/${total}`}>
            <i style={{ width: `${total ? Math.round((done / total) * 100) : 0}%` }} />
          </span>
        </span>
      }
    />
  )
}

/** A titled group of tiles. A single group needs no title. */
function Group({ id, title, tone, tiles, sub }: { id: string; title?: string; tone?: string; tiles: LabSummary[]; sub?: (l: LabSummary) => string | undefined }) {
  return (
    <section className={`group ${tone ? `t-${tone}` : ''}`} aria-labelledby={title ? `g-${id}` : undefined}>
      {title ? (
        <h2 className="group-h" id={`g-${id}`}>
          {tone && <span className="terr-dot" aria-hidden="true" />}
          {title} <small>{tiles.length}</small>
        </h2>
      ) : (
        <h2 className="sr-only">{t('a11y.allTiles', { n: tiles.length })}</h2> // the tiles' h3 headings need a level 2 above them
      )}
      <div className="grid-cards">
        {tiles.map((l) => (
          <LabTile key={l.id} l={l} sub={sub?.(l)} />
        ))}
      </div>
    </section>
  )
}

export function Labs() {
  const { cur } = useApp()
  const prog = useProgress()
  const trackOf = useTrackOf()
  const [q, setQ] = useState('')
  const [track, setTrack] = useState('')
  if (!cur) return null
  const labs = search(
    Object.values(cur.labs).filter((l) => l.kind === 'lab' && (!track || trackOf.get(l.module)?.track === track)),
    q,
    (l) => `${l.title} ${l.summary} ${l.concepts.join(' ')}`,
  ).sort((a, b) => (trackOf.get(a.module)?.order ?? 99) - (trackOf.get(b.module)?.order ?? 99))
  const done = Object.values(cur.labs).filter((l) => l.kind === 'lab' && activityDone(l.kind, prog.labs[l.id])).length
  const total = Object.values(cur.labs).filter((l) => l.kind === 'lab').length
  // one group per territory, in the order of the course; with a single group the heading would only repeat the filter
  const groups: { id: string; title: string; tone?: string; tiles: LabSummary[] }[] = []
  for (const l of labs) {
    const id = trackOf.get(l.module)?.track || 'other'
    let g = groups.find((x) => x.id === id)
    if (!g) groups.push((g = { id, title: trackOf.get(l.module)?.trackTitle || '', tone: cur.tracks.find((x) => x.id === id)?.accent || 'blue', tiles: [] }))
    g.tiles.push(l)
  }

  return (
    <div className="page labs-page practice">
      <ListHead title={t('labs.title')} lede={t('labs.lede')} done={done} total={total} what={t('labs.practised')} />
      <div className="filters">
        <div className="search-in">
          <Icon name="search" size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('labs.search')} aria-label={t('labs.search')} />
        </div>
        <label className="select-in">
          <span className="sr-only">{t('learn.title')}</span>
          <select value={track} onChange={(e) => setTrack(e.target.value)}>
            <option value="">{t('labs.allPaths')}</option>
            {cur.tracks.filter((tr) => Object.values(cur.labs).some((l) => l.kind === 'lab' && trackOf.get(l.module)?.track === tr.id)).map((tr) => ( // only courses that have labs
              <option key={tr.id} value={tr.id}>
                {tr.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      {groups.map((g) => (
        <Group key={g.id} id={g.id} title={groups.length > 1 ? g.title : undefined} tone={groups.length > 1 ? g.tone : undefined} tiles={g.tiles} />
      ))}
      {labs.length === 0 && <p className="muted">{t('pal.none')}</p>}
    </div>
  )
}

function LabTile({ l, sub }: { l: LabSummary; sub?: string }) {
  const prog = useProgress()
  const s = labStatus(prog.labs[l.id])
  return (
    <a className={`tile ${s} ${l.kind === 'incident' ? 'incident' : ''}`} href={labHref(l.id)}>
      <div className="tile-top">
        <Icon name={l.kind === 'incident' ? 'siren' : l.kind === 'challenge' ? 'flag' : 'flask'} />
        <LabStatusPill s={s} />
      </div>
      <h3>{l.title}</h3>
      <p>{l.summary}</p>
      <div className="tile-foot">
        <span>
          <Icon name="clock" size={13} /> {t('ui.minutes', { n: l.minutes })}
        </span>
        <LevelDots level={l.level} />
        {sub && <span className="tile-sub">{sub}</span>}
      </div>
    </a>
  )
}

export function Incidents() {
  const { cur } = useApp()
  const prog = useProgress()
  const trackOf = useTrackOf()
  const [lvl, setLvl] = useState(0)
  if (!cur) return null
  const all = Object.values(cur.labs).filter((l) => l.kind === 'incident')
  const list = all.filter((l) => !lvl || l.level === lvl).sort((a, b) => a.level - b.level || (trackOf.get(a.module)?.order ?? 0) - (trackOf.get(b.module)?.order ?? 0))
  const solved = all.filter((l) => activityDone(l.kind, prog.labs[l.id])).length
  const names = [t('inc.easy'), t('inc.medium'), t('inc.hard')]
  // one group per difficulty; a single group (a difficulty chosen) needs no title
  const groups = [...new Set(list.map((l) => l.level))].sort().map((n) => ({ n, tiles: list.filter((l) => l.level === n) }))
  return (
    <div className="page incidents-page practice">
      <ListHead title={t('inc.centerTitle')} lede={t('inc.centerLede')} done={solved} total={all.length} what={t('inc.solved')} />
      <div className="filters">
        <div className="chips" role="group" aria-label={t('inc.difficulty')}>
          {[0, 1, 2, 3].map((n) => (
            <button key={n} className={`chip ${lvl === n ? 'on' : ''}`} onClick={() => setLvl(n)} aria-pressed={lvl === n}>
              {n ? names[n - 1] : t('labs.all')}
            </button>
          ))}
        </div>
        <details className="more method-d">
          <summary>{t('inc.howTo')}</summary>
          <ol>
            {(['1', '2', '3', '4', '5'] as const).map((k) => (
              <li key={k}>{t(`inc.method${k}` as 'inc.method1')}</li>
            ))}
          </ol>
        </details>
      </div>
      {groups.map((g) => (
        <Group key={g.n} id={`level-${g.n}`} title={groups.length > 1 ? names[g.n - 1] || t('ui.level', { n: g.n }) : undefined} tiles={g.tiles} sub={(l) => trackOf.get(l.module)?.trackTitle} />
      ))}
    </div>
  )
}

/** Challenges: an end state to reach without steps. They are also part of the practice arena course (with the
 * incidents and the triage); this list is Practice's own view of them, so the tab never leaves Practice. */
export function Challenges() {
  const { cur } = useApp()
  const prog = useProgress()
  const trackOf = useTrackOf()
  if (!cur) return null
  const all = Object.values(cur.labs)
    .filter((l) => l.kind === 'challenge')
    .sort((a, b) => a.level - b.level || (trackOf.get(a.module)?.order ?? 0) - (trackOf.get(b.module)?.order ?? 0))
  const verified = all.filter((l) => activityDone(l.kind, prog.labs[l.id])).length // a challenge is completed by verifying it
  const arena = cur.tracks.find((tr) => tr.id === 'practice')
  return (
    <div className="page challenges-page practice">
      <ListHead title={t('chl.title')} lede={t('chl.lede')} done={verified} total={all.length} what={t('chl.verified')} />
      {arena && (
        <p className="muted list-note">
          {t('chl.inCourse')} <a href={trackHref(arena.id)}>{arena.title}</a>
        </p>
      )}
      <Group id="challenges" tiles={all} />
    </div>
  )
}
