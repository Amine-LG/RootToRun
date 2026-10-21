import type { ReactNode } from 'react'
import type { Curriculum, Route, Track } from '../lib/data'
import { getLang, t } from '../lib/i18n'
import type { Progress } from '../lib/progress'
import { activityDone } from '../lib/standing'
import { buildsOn, territoryOnRoute } from '../lib/routes'
import { trackProgress } from '../pages/Home'
import { trackHref } from '../lib/urls'
import { Icon } from './ui'
import { duration, trackTime } from '../lib/studytime'

const lessonsN = (n: number) => (n === 1 ? t('learn.lessonOne') : t('map.lessonsN', { n }))

/** "Builds on Linux and Containers": the courses a course assumes, as text (a map row is one link) or as links. */
export function BuildsOn({ cur, id, links }: { cur: Curriculum; id: string; links?: boolean }) {
  const from = buildsOn(cur, id).map((x) => cur.tracks.find((tr) => tr.id === x)).filter((x): x is Track => !!x)
  if (!from.length) return <>{t('ln.noPrereq')}</>
  const marker = '\u0001'
  const [pre, post] = t('ln.builds', { names: marker }).split(marker)
  const names = from.map((x) => x.short || x.title)
  let parts: { type: string; value: string }[]
  try {
    parts = new Intl.ListFormat(getLang(), { style: 'long', type: 'conjunction' }).formatToParts(names)
  } catch {
    parts = names.flatMap((n, i) => [...(i ? [{ type: 'literal', value: ', ' }] : []), { type: 'element', value: n }])
  }
  let k = -1
  return (
    <>
      {pre}
      {parts.map((p, i) => {
        if (p.type !== 'element') return p.value
        k++
        return links ? <a key={i} href={trackHref(from[k].id)}>{p.value}</a> : p.value
      })}
      {post}
    </>
  )
}

/** The courses in the order they build, one quiet row each: what it is, how many lessons, how far you are, what it builds
 * on. A chosen route fills the courses it crosses and leaves the rest outlined; nothing is ever locked or hidden. The
 * practice arena sits apart below, because it is open at any time. `here` is the course holding the learner's next lesson. */
export function JourneyMap({ cur, prog, route, here }: { cur: Curriculum; prog: Progress; route?: Route | null; here?: string | null }) {
  const lands = cur.tracks.filter((tr) => tr.id !== 'practice')
  const arena = cur.tracks.find((tr) => tr.id === 'practice')
  /** One row: a node, the course (title, one-line purpose, size and what it builds on) and, once started, how far you are. */
  const row = (tr: Track, o: { node: ReactNode; count: string; done: number; of: number; doneText: string; extra?: string }) => {
    const on = territoryOnRoute(cur, route, tr.id)
    const isHere = here === tr.id
    const started = o.done > 0
    const tag = isHere ? (started ? t('learn.continueHere') : t('learn.startHere')) : on === 'on' ? t('ln.onRoute') : on === 'part' ? t('ln.partRoute') : tr.id === 'practice' ? t('map.arenaEyebrow') : ''
    return (
      <>
        <span className="jm-node" aria-hidden="true">{o.node}</span>
        <div className="jm-body">
          <h3 className="jm-t">
            <a href={trackHref(tr.id)} aria-current={isHere ? 'true' : undefined}>
              {o.extra && <span className="sr-only">{o.extra}</span>}
              {tr.title}
            </a>
            {tag && <span className="jm-tag">{tag}</span>}
            {isHere && on && on !== 'off' && <span className="sr-only"> ({on === 'on' ? t('ln.onRoute') : t('ln.partRoute')})</span>}
          </h3>
          <p className="jm-p">{tr.tagline}</p>
          <p className="jm-from">
            {o.count} · <BuildsOn cur={cur} id={tr.id} />
            {tr.status === 'coming-soon' && ` · ${t('learn.comingSoonPill')}`}
          </p>
        </div>
        {started && (
          <div className="jm-prog">
            <span className="jm-n">{o.doneText}</span>
            <span className="jm-bar" role="progressbar" aria-label={t('map.progressOf', { name: tr.title })} aria-valuenow={Math.round((100 * o.done) / o.of)} aria-valuemin={0} aria-valuemax={100}>
              <i style={{ width: `${(100 * o.done) / o.of}%` }} />
            </span>
          </div>
        )}
      </>
    )
  }
  const cls = (tr: Track, ...more: string[]) => ['jm-row', `t-${tr.accent || 'blue'}`, territoryOnRoute(cur, route, tr.id) || '', here === tr.id ? 'here' : '', ...more].filter(Boolean).join(' ')

  const arenaIds = arena ? arena.modules.flatMap((m) => cur.modules.find((x) => x.id === m)?.labs || []).filter((id) => cur.labs[id]) : []
  const arenaSolved = arenaIds.filter((id) => activityDone(cur.labs[id].kind, prog.labs[id])).length

  return (
    <div className={`jmap-wrap ${route ? 'has-route' : ''}`}>
      <ol className="jmap" data-route={route?.id || undefined} aria-label={t('map.aria')}>
        {lands.map((tr, i) => {
          const p = trackProgress(cur, prog, tr.id)
          const tm = trackTime(cur, prog, tr.id)
          const complete = p.total > 0 && p.done === p.total
          const count = p.total ? `${lessonsN(p.total)} · ${duration(tm.minutes)}` : t('map.empty')
          const doneText = t('map.doneOf', { n: p.done, of: p.total }) + (tm.left > 0 && p.done > 0 ? ` · ${t('time.left', { d: duration(tm.left) })}` : '')
          return (
            <li key={tr.id} className={cls(tr, 'jm-stop', complete ? 'done' : '')} data-testid={`map-${tr.id}`}>
              {row(tr, { node: complete ? <Icon name="check" size={18} /> : i + 1, count, done: p.done, of: p.total, doneText, extra: `${i + 1}. ` })}
            </li>
          )
        })}
      </ol>
      {arena && (
        <div className={cls(arena, 'jm-practice')} data-testid="map-practice">
          {row(arena, { node: <Icon name={arena.icon || 'target'} size={20} />, count: t('map.arenaN', { n: arenaIds.length }), done: arenaSolved, of: arenaIds.length, doneText: t('ln.solvedN', { n: arenaSolved }) })}
        </div>
      )}
    </div>
  )
}
