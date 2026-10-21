// "To practise this yourself": one line at the top of a lesson or lab naming the tools its commands use and the kind
// of machine or cluster they ran on, each linked to its part of the setup guide (/setup). Derived from the content
// (backend/academy/tools.py), never written per lesson.
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { setupHref } from '../lib/urls'
import { Icon } from './ui'
import './commands.css'

export type Where = 'host' | 'cluster' | 'cluster-admin' | 'lab'

/** A version worth showing next to a tool: only something that looks like one (recordings sometimes hold a commit). */
const version = (v?: string) => (v && /^v?\d+\.\d+(\.\d+)?$/.test(v) ? v.replace(/^v/, '') : '')

export function Prereqs({ tools, where, versions = {} }: { tools: string[]; where: Where; versions?: Record<string, string | undefined> }) {
  const { cur } = useApp()
  const known = new Map((cur?.tools ?? []).map((x) => [x.id, x]))
  const list = tools.filter((id) => known.has(id))
  const cluster = where !== 'host'
  if (!list.length && !cluster) return null
  return (
    <aside className="prereqs" aria-label={t('setup.prereqAria')} data-testid="prereqs">
      <Icon name="wrench" size={15} />
      <span className="prereqs-label">{t(where === 'lab' ? 'setup.needLab' : 'setup.need')}</span>
      <ul className="prereqs-list">
        {list.map((id) => (
          <li key={id}>
            <a href={setupHref(id)}>{known.get(id)!.name}</a>
            {version(versions[id]) && <span className="muted"> {t('setup.recordedWith', { v: version(versions[id]) })}</span>}
          </li>
        ))}
        {cluster && (
          <li>
            <a href={setupHref('cluster')}>{t(where === 'cluster-admin' ? 'setup.clusterAdmin' : where === 'lab' ? 'setup.clusterLab' : 'setup.clusterUser')}</a>
          </li>
        )}
      </ul>
      <span className="prereqs-where">{t(where === 'lab' ? 'setup.nothingRunsLab' : 'setup.nothingRuns')}</span>
    </aside>
  )
}
