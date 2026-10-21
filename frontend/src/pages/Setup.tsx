// The setup guide: what practising outside the website needs, one section per tool (anchor = tool id, the target of
// the prerequisite line on lessons and labs), and the cluster. Which lessons use a tool is derived from their commands
// by the server (backend/academy/tools.py); the tool texts come from content/en/tools.yaml.
import '../components/commands.css'
import { PageHead } from '../components/PageHead'
import { CopyButton, Icon } from '../components/ui'
import { useApp } from '../lib/app'
import type { Curriculum } from '../lib/data'
import { t } from '../lib/i18n'
import { MdInline } from '../lib/md'
import { lessonHref, trackHref } from '../lib/urls'

/** Lessons in course order: tracks, then their modules, then the modules' lessons. */
function lessonOrder(cur: Curriculum): { id: string; track: string }[] {
  const mods = new Map(cur.modules.map((m) => [m.id, m]))
  return cur.tracks.flatMap((tr) => tr.modules.flatMap((m) => (mods.get(m)?.lessons ?? []).filter((l) => cur.lessons[l]).map((id) => ({ id, track: tr.id }))))
}

export default function Setup() {
  const { cur } = useApp()
  if (!cur) return null
  const order = lessonOrder(cur)
  const tracks = new Map(cur.tracks.map((tr) => [tr.id, tr]))
  const usedBy = (tool: string) => order.filter((x) => cur.lessons[x.id].tools?.includes(tool))
  const labsUsing = (tool: string) => Object.values(cur.labs).filter((lab) => lab.tools?.includes(tool)).length
  const mods = new Map(cur.modules.map((m) => [m.id, m]))
  const perTrack = cur.tracks.map((tr) => {
    const ls = order.filter((x) => x.track === tr.id).map((x) => cur.lessons[x.id])
    // labs, incidents and challenges listed by the track's modules (the practice arena has only those)
    const labs = tr.modules.flatMap((m) => mods.get(m)?.labs ?? []).map((id) => cur.labs[id]).filter(Boolean)
    const tools = (cur.tools ?? []).filter((tool) => ls.some((l) => l.tools?.includes(tool.id)) || labs.some((lab) => lab.tools?.includes(tool.id)))
    const where = ls.some((l) => l.record_on === 'cluster-admin') ? 'admin' : ls.some((l) => l.record_on === 'cluster') || labs.length ? 'user' : 'none'
    return { tr, tools, where }
  })
  return (
    <div className="page setup xp" data-testid="setup">
      <PageHead eyebrow={t('nav.reference')} title={t('setup.title')} lede={t('setup.lede')} />

      <section className="xp-section" aria-labelledby="setup-tracks">
        <h2 className="xp-section-h" id="setup-tracks">{t('setup.perTrack')}</h2>
        <p className="xp-section-sub">{t('setup.perTrackSub')}</p>
        <div className="table-wrap">
          <table className="setup-table">
            <thead>
              <tr>
                <th scope="col">{t('setup.colTrack')}</th>
                <th scope="col">{t('setup.colTools')}</th>
                <th scope="col">{t('setup.colCluster')}</th>
              </tr>
            </thead>
            <tbody>
              {perTrack.map(({ tr, tools, where }) => (
                <tr key={tr.id}>
                  <th scope="row"><a href={trackHref(tr.id)}>{tr.title}</a></th>
                  <td>
                    {tools.length ? tools.map((tool, i) => (
                      <span key={tool.id}>{i > 0 && ', '}<a href={`#${tool.id}`}>{tool.name}</a></span>
                    )) : '—'}
                  </td>
                  <td>{where === 'none' ? t('setup.noCluster') : <a href="#cluster">{t(where === 'admin' ? 'setup.clusterAdminShort' : 'setup.clusterUserShort')}</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="xp-section" aria-labelledby="setup-tools">
        <h2 className="xp-section-h" id="setup-tools">{t('setup.tools')}</h2>
        <p className="xp-section-sub">{t('setup.toolsSub')}</p>
        <ul className="setup-tools">
          {(cur.tools ?? []).map((tool) => {
            const lessons = usedBy(tool.id)
            const first = lessons[0]
            const labs = labsUsing(tool.id)
            return (
              <li key={tool.id} id={tool.id} className="setup-tool" data-testid="setup-tool" tabIndex={-1}>
                <h3>
                  {tool.name}
                  <small>
                    {lessons.length ? t(lessons.length === 1 ? 'setup.usedIn1' : 'setup.usedIn', { n: lessons.length }) : ''}
                    {labs ? `${lessons.length ? ' · ' : ''}${t(labs === 1 ? 'setup.usedInLabs1' : 'setup.usedInLabs', { n: labs })}` : ''}
                  </small>
                </h3>
                <p><MdInline text={tool.what} /></p>
                {first && (
                  <p className="setup-first">
                    {t('setup.firstUsed')} <a href={lessonHref(first.id)}>{cur.lessons[first.id].title}</a> ({tracks.get(first.track)?.title})
                  </p>
                )}
                <p>
                  <strong>{t('setup.install')}</strong>{' '}
                  {tool.install.map((l, i) => (
                    <span key={l.url}>{i > 0 && ' · '}<a href={l.url} target="_blank" rel="noopener noreferrer">{l.title}</a></span>
                  ))}
                </p>
                <p className="setup-verify">
                  <strong>{t('setup.verify')}</strong> <code>{tool.verify}</code> <CopyButton text={tool.verify} label={t('ui.copyCommand')} />
                </p>
                {tool.notes && <p className="muted"><MdInline text={tool.notes} /></p>}
              </li>
            )
          })}
          <li id="cluster" className="setup-tool" data-testid="setup-tool" tabIndex={-1}>
            <h3><Icon name="layers" size={16} /> {t('setup.clusterTitle')}</h3>
            <p><MdInline text={t('setup.clusterText')} /></p>
            <p><MdInline text={t('setup.clusterAdminText')} /></p>
            <p>
              <a href="/about#own-cluster">{t('setup.ownClusterLink')}</a> ·{' '}
              <a href="https://developers.redhat.com/products/openshift-local/overview" target="_blank" rel="noopener noreferrer">{t('setup.crcLink')}</a>
            </p>
          </li>
        </ul>
      </section>
    </div>
  )
}
