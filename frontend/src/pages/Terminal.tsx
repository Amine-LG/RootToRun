import { useMemo, useState } from 'react'
import { LiveTerminal, PracticeTerminal } from '../components/Term'
import { PageHead } from '../components/PageHead'
import { Callout, Icon, PageSkeleton, Spinner } from '../components/ui'
import { api } from '../lib/data'
import { useApp, useLoad } from '../lib/app'
import { t } from '../lib/i18n'
import '../practice.css'

const STARTERS = [
  'oc whoami',
  'oc get pods -l app=web -n academy-deploy',
  'oc get route,svc,pods -n academy-inc-selector',
  'oc describe svc web -n academy-inc-selector',
  'oc get events -n academy-inc-pull --field-selector reason=Failed',
  'oc auth can-i create projectrequests',
  'oc adm policy who-can list pods -n academy-access',
  'oc get pvc -n academy-inc-pvc',
]

export default function TerminalPage() {
  const { lang, meta, live } = useApp()
  const { data } = useLoad(() => api.commands(lang), [lang])
  const [tab, setTab] = useState<'practice' | 'live'>(live ? 'live' : 'practice')
  const [seed, setSeed] = useState<{ cmd: string; n: number } | undefined>()
  const starters = useMemo(() => {
    const tested = new Set((data || []).filter((c) => c.tested).map((c) => c.cmd))
    return STARTERS.filter((s) => tested.has(s))
  }, [data])
  if (!data) return <div className="page"><PageSkeleton /></div>

  return (
    <div className="page terminal-page practice">
      <PageHead
        eyebrow={t('nav.practice')}
        title={t('play.pageTitle')}
        lede={meta?.mode === 'cluster' && tab === 'live' ? t('play.ledeLive') : t('play.lede')}
        aside={
          meta?.mode === 'cluster' && (
            <div className="seg" role="tablist" aria-label={t('play.pageTitle')}>
              <button role="tab" aria-selected={tab === 'practice'} className={tab === 'practice' ? 'on' : ''} onClick={() => setTab('practice')}>
                {t('play.tabPractice')}
              </button>
              <button role="tab" aria-selected={tab === 'live'} className={tab === 'live' ? 'on' : ''} onClick={() => setTab('live')}>
                {t('play.tabLive')}
              </button>
            </div>
          )
        }
      />
      {tab === 'live' && meta?.mode === 'cluster' ? (
        live ? (
          <LiveTerminal seed={seed} height={520} />
        ) : (
          <Callout tone="warn" title={t('env.connectTitle')}>
            {t('env.connectText')} <a href="/connections">{t('nav.connections')}</a>
          </Callout>
        )
      ) : (
        <PracticeTerminal corpus={data} seed={seed} height={520} starters={starters} />
      )}
      <p className="muted small">
        {t('play.sideNote')} <a href="/commands">{t('play.browseAll')}</a>
      </p>
    </div>
  )
}
