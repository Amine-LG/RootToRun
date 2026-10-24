import { useEffect, useState } from 'react'
import { PageActions } from '../components/Contribute'
import { FlowDiagram } from '../components/FlowDiagram'
import { PageHead } from '../components/PageHead'
import { useOnline } from '../components/PageBoundary'
import { Callout, Icon, Spinner } from '../components/ui'
import { reloadPage, retrying } from '../lib/chunks'
import { DIAGRAMS } from '../lib/diagrams'
import { navigate } from '../lib/router'
import { t } from '../lib/i18n'
import '../explore.css'

// Explore: diagrams (static explanations of how parts relate) and models (interactive simulations). They are two
// catalogues with separate URLs, /studio/diagram/<id> and /studio/model/<id>, because an id can exist in both
// (a "storage" diagram and a "storage" model). A selection always renders exactly one item.

export type SimDef = { id: string; title: string; summary: string; concepts: string[]; Component: () => JSX.Element }
const simLoaders = import.meta.glob('../sims/index.ts') as Record<string, () => Promise<{ SIMS: SimDef[] }>>
const [simImport] = Object.values(simLoaders)
const simLoader = simImport && retrying(simImport)
let simCache: Promise<SimDef[]> | null = null
/** The models' code, loaded once. A failed load is forgotten, so the next request tries again (lib/chunks.ts). */
export function loadSims(): Promise<SimDef[]> {
  if (!simLoader) return Promise.resolve([])
  return (simCache ??= simLoader().then((m) => m.SIMS || [], (e) => {
    simCache = null
    throw e
  }))
}

/** The models, null while they load. A failed load is shown where the model would be (ModelFailed), never instead
 *  of the page around it: a lesson or a diagram is still worth reading. */
function useSims(): { sims: SimDef[] | null; failed: boolean; retry: () => void } {
  const [sims, setSims] = useState<SimDef[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [round, setRound] = useState(0)
  useEffect(() => {
    let live = true
    loadSims().then((s) => live && setSims(s), () => live && setFailed(true))
    return () => { live = false }
  }, [round])
  return { sims, failed, retry: () => (setFailed(false), setRound((n) => n + 1)) }
}

/** In place of a model that could not load: what happened (offline or not), and Try again or Reload. */
function ModelFailed({ onRetry }: { onRetry: () => void }) {
  const online = useOnline()
  return (
    <div data-testid="model-error">
      <Callout tone="warn" title={t('studio.modelFailed')}>
        <p>{t(online ? 'studio.modelFailedText' : 'studio.modelOffline')}</p>
        <p className="row">
          <button type="button" className="btn sm primary" onClick={onRetry} data-testid="model-retry">{t('app.pageRetry')}</button>
          <button type="button" className="btn sm" onClick={() => void reloadPage()}>{t('app.pageReload')}</button>
        </p>
      </Callout>
    </div>
  )
}

/** Older content refers to some diagrams by former ids. */
const LEGACY: Record<string, string> = { 'pod-lifecycle': 'control-loop', 'crc-vs-prod': 'enterprise' }

export function Diagram({ id }: { id: string }) {
  const d = DIAGRAMS.find((x) => x.id === (LEGACY[id] || id))
  return d ? <FlowDiagram d={d} /> : null
}

export function SimById({ id }: { id: string; bare?: boolean }) {
  const { sims, failed, retry } = useSims()
  if (failed) return <ModelFailed onRetry={retry} />
  if (!sims) return <Spinner />
  const s = sims.find((x) => x.id === id)
  if (!s) return null
  return <s.Component />
}

type Item = { kind: 'model' | 'diagram'; id: string; title: string; summary: string }

/** Resolve a Studio path: "diagram/<id>", "model/<id>", or a legacy bare id (diagram first, then model). */
function resolve(view: string, items: Item[]): Item | undefined {
  const [k, id] = view.includes('/') ? (view.split('/') as [string, string]) : ['', view]
  const want = LEGACY[id] || id
  if (k === 'diagram' || k === 'model') return items.find((x) => x.kind === k && x.id === want)
  return items.find((x) => x.kind === 'diagram' && x.id === want) || items.find((x) => x.kind === 'model' && x.id === want)
}

function usePrefFlag(key: string): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(() => {
    try {
      return localStorage.getItem(key) === '1'
    } catch {
      return false
    }
  })
  return [v, (x) => {
    setV(x)
    try {
      localStorage.setItem(key, x ? '1' : '0')
    } catch {
      /* private mode */
    }
  }]
}

export default function Studio({ view }: { view: string }) {
  const { sims, failed, retry } = useSims()
  const [hideList, setHideList] = usePrefFlag('osa.studio.hideList')
  const items: Item[] = [
    ...(sims || []).map((s) => ({ kind: 'model' as const, id: s.id, title: s.title, summary: s.summary })),
    ...DIAGRAMS.map((d) => ({ kind: 'diagram' as const, id: d.id, title: d.title, summary: d.caption || '' })),
  ]
  // Until the models have loaded, a model (or the default view, which is the first model) cannot be resolved yet:
  // wait instead of flashing a different item or an empty stage.
  const waiting = sims === null && !failed && (view === 'index' || !resolve(view, items))
  const selected = waiting ? undefined : view === 'index' ? items.find((x) => x.kind === 'model') || items[0] : resolve(view, items)
  const key = (x: Item) => `${x.kind}/${x.id}`
  const isOn = (kind: Item['kind'], id: string) => selected?.kind === kind && selected.id === id
  const select = (k: string) => navigate(`/studio/${k}`, { replace: true })
  const diagram = selected?.kind === 'diagram' ? DIAGRAMS.find((d) => d.id === selected.id) : undefined
  const sim = selected?.kind === 'model' ? sims?.find((s) => s.id === selected.id) : undefined
  const at = selected ? items.findIndex((x) => isOn(x.kind, x.id)) : -1
  const [prev, next] = [items[at - 1], items[at + 1]].map((x) => (at >= 0 ? x : undefined))
  const kindLabel = (k: Item['kind']) => (k === 'model' ? t('xp.kindModel') : t('xp.kindDiagram'))

  return (
    <div className="page studio wide xp">
      <PageHead eyebrow={t('nav.explore')} title={t('nav.studio')} lede={t('studio.lede')}
        actions={selected && view !== 'index' && <PageActions ctx={{ type: selected.kind, id: selected.id, title: selected.title, area: t('nav.explore') }} />} />
      <div className={`studio-ws ${hideList ? 'list-hidden' : ''}`}>
        <aside className="studio-list" aria-label={t('studio.listLabel')}>
          <label className="studio-select">
            <span className="sr-only">{t('studio.listLabel')}</span>
            <select value={selected ? key(selected) : ''} onChange={(e) => select(e.target.value)}>
              {sims && sims.length > 0 && (
                <optgroup label={t('studio.sims')}>
                  {sims.map((s) => (
                    <option key={s.id} value={`model/${s.id}`}>
                      {s.title}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label={t('studio.diagrams')}>
                {DIAGRAMS.map((d) => (
                  <option key={d.id} value={`diagram/${d.id}`}>
                    {d.title}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <div className="studio-groups">
            <div className="menu-h">{t('studio.sims')}</div>
            {sims === null && !failed && <Spinner label={t('studio.loadingModels')} />}
            {failed && (
              <p className="small">
                {t('studio.modelsMissing')} <button type="button" className="linkish" onClick={retry}>{t('app.pageRetry')}</button>
              </p>
            )}
            {(sims || []).map((s) => (
              <button key={s.id} className={`studio-item ${isOn('model', s.id) ? 'on' : ''}`} onClick={() => select(`model/${s.id}`)} aria-current={isOn('model', s.id) ? 'true' : undefined}>
                {s.title}
              </button>
            ))}
            <div className="menu-h">{t('studio.diagrams')}</div>
            {DIAGRAMS.map((d) => (
              <button key={d.id} className={`studio-item ${isOn('diagram', d.id) ? 'on' : ''}`} onClick={() => select(`diagram/${d.id}`)} aria-current={isOn('diagram', d.id) ? 'true' : undefined}>
                {d.title}
              </button>
            ))}
          </div>
        </aside>
        <section className="studio-stage xp-stage" aria-live="polite" data-kind="explore" data-testid="studio-stage">
          {selected && (
            <div className="xp-stagebar">
              <span className={`xp-kind ${selected.kind}`}>
                <Icon name={selected.kind === 'model' ? 'layers' : 'map'} size={15} /> {kindLabel(selected.kind)}
              </span>
              <span className="xp-hint">{selected.kind === 'model' ? t('studio.modelVerb') : t('studio.diagramVerb')}</span>
              <button className="linkish small studio-list-toggle" onClick={() => setHideList(!hideList)} aria-expanded={!hideList} data-testid="studio-list-toggle" title={hideList ? t('studio.showList') : t('studio.hideList')}>
                <Icon name="list" size={14} /> {hideList ? t('xp.showList') : t('xp.hideList')}
              </button>
            </div>
          )}
          {selected && (
            <div className="xp-swap" key={key(selected)}>
              {diagram && <FlowDiagram d={diagram} />}
              {selected.kind === 'model' && !sim && <Spinner label={t('studio.loadingModels')} />}
              {sim && <sim.Component />}
            </div>
          )}
          {waiting && <Spinner label={t('studio.loadingModels')} />}
          {!selected && !waiting && failed && <ModelFailed onRetry={retry} />}
          {!selected && !waiting && sims !== null && <Callout tone="info">{t('studio.pick')}</Callout>}
          {selected && (prev || next) && (
            <nav className="xp-pager" aria-label={t('xp.pagerLabel')}>
              {prev ? (
                <a className="xp-pager-link prev" href={`/studio/${key(prev)}`}>
                  <Icon name="back" size={16} />
                  <span>
                    <small>{t('xp.prev')} · {kindLabel(prev.kind)}</small>
                    {prev.title}
                  </span>
                </a>
              ) : (
                <span />
              )}
              {next && (
                <a className="xp-pager-link next" href={`/studio/${key(next)}`}>
                  <span>
                    <small>{t('xp.next')} · {kindLabel(next.kind)}</small>
                    {next.title}
                  </span>
                  <Icon name="arrow" size={16} />
                </a>
              )}
            </nav>
          )}
        </section>
      </div>
    </div>
  )
}
