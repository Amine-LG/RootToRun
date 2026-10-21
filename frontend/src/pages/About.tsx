import { useEffect } from 'react'
import { Callout, Icon } from '../components/ui'
import { useApp } from '../lib/app'
import { COPYRIGHT, CREATOR } from '../lib/brand'
import { t } from '../lib/i18n'
import { Md } from '../lib/md'
import { reducedMotion } from '../lib/reveal'
import '../pages.css'

export default function About() {
  const { meta, cur } = useApp()
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1))
    if (id) document.getElementById(id)?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth' })
  }, [])
  const recorded = cur ? Object.values(cur.labs).filter((l) => l.recorded).length : 0
  const total = cur ? Object.keys(cur.labs).length : 0
  return (
    <div className="page pg pg-about">
      <header className="pg-head">
        <div className="eyebrow">{t('about.eyebrow')}</div>
        <h1>{t('about.title', { brand: t('app.name') })}</h1>
        <p className="pg-purpose">{t('about.lede')}</p>
      </header>

      <ul className="ab-facts">
        <li>
          <a href="#tested">
            <strong>{t('about.factRecordedN', { recorded, total })}</strong>
            <span>{t('about.factRecorded')}</span>
          </a>
        </li>
        <li>
          <a href="#privacy">
            <strong>{t('about.factPrivateN')}</strong>
            <span>{t('about.factPrivate')}</span>
          </a>
        </li>
        <li>
          <a href="#safety">
            <strong>{t('about.factSafeN')}</strong>
            <span>{t('about.factSafe')}</span>
          </a>
        </li>
      </ul>

      <section className="ab-sec" id="tested" aria-labelledby="ab-tested">
        <h2 id="ab-tested">
          <Icon name="check" /> {t('about.testedTitle')}
        </h2>
        <Md text={t('about.tested', { recorded, total })} />
      </section>

      <section className="ab-sec" id="modes" aria-labelledby="ab-modes">
        <h2 id="ab-modes">
          <Icon name="layers" /> {t('about.modesTitle')}
        </h2>
        <Md text={t('about.modes')} />
        <Callout tone="info">{t('about.currentMode', { mode: meta?.mode || '?' })}</Callout>
      </section>

      <section className="ab-sec" id="own-cluster" aria-labelledby="ab-own">
        <h2 id="ab-own">
          <Icon name="terminal" /> {t('about.ownTitle')}
        </h2>
        <Md text={t('about.own')} />
      </section>

      <section className="ab-sec" id="safety" aria-labelledby="ab-safety">
        <h2 id="ab-safety">
          <Icon name="shield" /> {t('about.safetyTitle')}
        </h2>
        <Md text={t('about.safety')} />
      </section>

      <section className="ab-sec" id="privacy" aria-labelledby="ab-privacy">
        <h2 id="ab-privacy">
          <Icon name="lock" /> {t('about.privacyTitle')}
        </h2>
        <Md text={t('about.privacy')} />
      </section>

      <section className="ab-sec" id="credits" aria-labelledby="ab-credits">
        <h2 id="ab-credits">
          <Icon name="book" /> {t('about.creditsTitle')}
        </h2>
        <Md text={t('about.credits', { brand: t('app.name'), creator: CREATOR.name, creatorUrl: CREATOR.url })} />
      </section>

      <section className="ab-sec" id="licences" aria-labelledby="ab-licences">
        <h2 id="ab-licences">
          <Icon name="file" /> {t('about.licencesTitle')}
        </h2>
        <Md text={t('about.licences', { copyright: COPYRIGHT, brand: t('app.name') })} />
        {meta?.version && (
          <p className="small muted" data-testid="build-version">
            {meta.commit ? t('about.versionCommit', { v: meta.version, c: meta.commit }) : t('about.version', { v: meta.version })}
          </p>
        )}
      </section>

      <section className="ab-sec" id="trademarks" aria-labelledby="ab-legal">
        <h2 id="ab-legal">
          <Icon name="file" /> {t('about.legalTitle')}
        </h2>
        <Md text={t('about.legal', { brand: t('app.name') })} />
      </section>
    </div>
  )
}
