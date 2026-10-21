import { PageActions } from '../components/Contribute'
import { ExplainCard } from '../components/Learn'
import { PageBar, PageHead } from '../components/PageHead'
import { Callout, Crumbs, Icon, Refs, PageSkeleton, Spinner } from '../components/ui'
import { api } from '../lib/data'
import { useApp, useLoad } from '../lib/app'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { labHref } from '../lib/urls'

export default function Handbook() {
  const { cur } = useApp()
  if (!cur) return null
  return (
    <div className="page handbook xp">
      <PageHead eyebrow={t('nav.reference')} title={t('hb.title')} lede={t('hb.lede')} />
      <section className="xp-section" aria-labelledby="hb-runbooks">
        <h2 className="xp-section-h" id="hb-runbooks">
          {t('hb.runbooks')} <small>{cur.runbooks.length}</small>
        </h2>
        <p className="xp-section-sub">{t('xp.runbooksSub')}</p>
        <div className="grid-cards">
          {cur.runbooks.map((r) => (
            <a key={r.id} className="tile" href={`/runbook/${r.id}`}>
              <div className="tile-top xp-tile-top">
                <span className="xp-tile-kind">
                  <Icon name="wrench" size={15} /> {t('xp.kindRunbook')}
                </span>
                <Icon name="arrow" size={16} className="xp-tile-go" />
              </div>
              <h3>{r.title}</h3>
              <p>
                <MdInline text={r.when} />
              </p>
            </a>
          ))}
        </div>
      </section>
      <section className="xp-section" aria-labelledby="hb-cases">
        <h2 className="xp-section-h" id="hb-cases">
          {t('hb.cases')} <small>{cur.cases.length}</small>
        </h2>
        <p className="xp-section-sub">{t('xp.casesSub')}</p>
        <div className="grid-cards">
          {cur.cases.map((c) => (
            <a key={c.id} className="tile" href={`/case/${c.id}`}>
              <div className="tile-top xp-tile-top">
                <span className="xp-tile-kind">
                  <Icon name="layers" size={15} /> {t('xp.kindCase')}
                </span>
                <Icon name="arrow" size={16} className="xp-tile-go" />
              </div>
              <h3>{c.title}</h3>
              <p>{c.concepts.map((x) => cur.concepts[x]?.title).filter(Boolean).join(' · ')}</p>
            </a>
          ))}
        </div>
      </section>
    </div>
  )
}

export function RunbookPage({ id }: { id: string }) {
  const { lang, cur } = useApp()
  const { data: r, err } = useLoad(() => api.runbook(id, lang), [id, lang])
  if (err) return <div className="page"><Callout tone="bad">{err}</Callout></div>
  if (!r || !cur) return <div className="page"><PageSkeleton /></div>
  return (
    <div className="page runbook xp xp-article">
      <PageBar actions={<PageActions ctx={{ type: 'runbook', id, title: r.title, area: t('nav.handbook'), source: r.source }} />}>
        <Crumbs items={[[t('nav.handbook'), '/handbook'], [r.title]]} />
      </PageBar>
      <p className="xp-eyebrow">
        <Icon name="wrench" size={15} /> {t('hb.runbook')}
      </p>
      <h1>{r.title}</h1>
      <Callout tone="info" title={t('hb.when')}>
        <Md text={r.when} />
      </Callout>
      <Callout tone="warn" title={t('hb.severity')}>
        <Md text={r.severity_guide} />
      </Callout>
      {r.steps.map((s: { title: string; body: string }, i: number) => (
        <section key={i}>
          <h2>{s.title}</h2>
          <Md text={s.body} />
        </section>
      ))}
      {r.decision_tree?.length > 0 && (
        <section>
          <h2>{t('hb.decide')}</h2>
          <div className="dtree">
            {/* the content files write the branches as `yes:` / `no:`, which YAML reads as the booleans true / false */}
            {r.decision_tree.map((d: { question: string; yes?: string; no?: string; true?: string; false?: string }, i: number) => (
              <div key={i} className="dnode">
                <div className="dq">{d.question}</div>
                <div className="dyes">
                  <strong>{t('hb.yes')}</strong> {d.yes ?? d.true}
                </div>
                <div className="dno">
                  <strong>{t('hb.no')}</strong> {d.no ?? d.false}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
      <section>
        <h2>{t('hb.escalate')}</h2>
        <ul>
          {r.escalate.map((e: string, i: number) => (
            <li key={i}>
              <MdInline text={e} />
            </li>
          ))}
        </ul>
      </section>
      {r.labs?.length > 0 && (
        <section>
          <h2>{t('hb.practise')}</h2>
          <div className="module-labs">
            {r.labs.map((l: string) =>
              cur.labs[l] ? (
                <a key={l} href={labHref(l)} className={`lab-chip ${cur.labs[l].kind === 'incident' ? 'incident' : ''}`}>
                  <Icon name={cur.labs[l].kind === 'incident' ? 'siren' : 'flask'} size={14} /> {cur.labs[l].title}
                </a>
              ) : null,
            )}
          </div>
        </section>
      )}
    </div>
  )
}

export function CasePage({ id }: { id: string }) {
  const { lang } = useApp()
  const { data: c, err } = useLoad(() => api.caseStudy(id, lang), [id, lang])
  if (err) return <div className="page"><Callout tone="bad">{err}</Callout></div>
  if (!c) return <div className="page"><PageSkeleton /></div>
  const owners = Object.entries(c.ownership as Record<string, string[]>).filter(([, v]) => v.length)
  return (
    <div className="page case xp xp-article">
      <PageBar actions={<PageActions ctx={{ type: 'case', id, title: c.title, area: t('nav.handbook'), source: c.source }} />}>
        <Crumbs items={[[t('nav.handbook'), '/handbook'], [c.title]]} />
      </PageBar>
      <p className="xp-eyebrow">
        <Icon name="layers" size={15} /> {t('hb.case')}
      </p>
      <h1>{c.title}</h1>
      <h2>{t('hb.context')}</h2>
      <Md text={c.context} />
      <Callout tone="bad" icon="siren" title={t('hb.situation')}>
        <Md text={c.situation} />
      </Callout>
      <h2>{t('hb.who')}</h2>
      <div className="owners">
        {owners.map(([k, v]) => (
          <div key={k} className="owner">
            <div className="owner-h">{k}</div>
            <ul>
              {v.map((x, i) => (
                <li key={i}>
                  <MdInline text={x} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="grid3 case-lists">
        {(
          [
            ['hb.evidence', c.evidence],
            ['hb.approvals', c.approvals],
            ['hb.automate', c.automate],
          ] as const
        ).map(([k, list]) => (
          <div key={k}>
            <h3>{t(k)}</h3>
            <ul>
              {(list as string[]).map((x, i) => (
                <li key={i}>
                  <MdInline text={x} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <h2>{t('hb.discuss')}</h2>
      <div className="qa">
        {c.discussion.map((q: { q: string; a: string }, i: number) => (
          <details key={i}>
            <summary>
              <Md text={q.q} />
            </summary>
            <Md text={q.a} />
          </details>
        ))}
      </div>
      {c.explain?.map((e: any, i: number) => (
        <ExplainCard key={i} e={e} k={`case:${id}:${i}`} />
      ))}
      <Refs refs={c.references} />
    </div>
  )
}
