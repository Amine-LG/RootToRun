// "Understand this command": an optional explanation under a demonstrated or practised command, closed by default
// (progressive disclosure), opened with a real button that reports its state (aria-expanded). Authored per step in the
// lesson YAML (`understand:`, backend/academy/curriculum.py Understand) and verified against the sources it lists.
import { useId, useState } from 'react'
import type { Understand as U } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { MdInline } from '../lib/md'
import { Icon } from './ui'
import './commands.css'

export function Understand({ u }: { u: U }) {
  const [open, setOpen] = useState(false)
  const { cur } = useApp()
  const panel = useId()
  const concepts = u.concepts.map((c) => cur?.concepts[c]).filter(Boolean)
  return (
    <div className={`understand ${open ? 'open' : ''}`} data-testid="understand">
      <button type="button" className="understand-toggle" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)} data-testid="understand-toggle">
        <Icon name="book" size={15} />
        <span>{t('cmdx.toggle')}</span>
        <Icon name={open ? 'minus' : 'plus'} size={14} />
      </button>
      <div id={panel} className="understand-body" hidden={!open} data-testid="understand-body">
        <p className="understand-purpose">
          <MdInline text={u.purpose} />
        </p>
        {u.parts.length > 0 && (
          <dl className="understand-parts">
            {u.parts.map((p) => (
              <div key={p.text}>
                <dt>
                  <code>{p.text}</code>
                </dt>
                <dd>
                  <MdInline text={p.means} />
                </dd>
              </div>
            ))}
          </dl>
        )}
        {u.needs && (
          <p>
            <strong>{t('cmdx.needs')}</strong> <MdInline text={u.needs} />
          </p>
        )}
        {u.output && (
          <p>
            <strong>{t('cmdx.output')}</strong> <MdInline text={u.output} />
          </p>
        )}
        {u.mistakes.length > 0 && (
          <>
            <p className="understand-h">
              <strong>{t('cmdx.mistakes')}</strong>
            </p>
            <ul>
              {u.mistakes.map((m) => (
                <li key={m}>
                  <MdInline text={m} />
                </li>
              ))}
            </ul>
          </>
        )}
        {u.caution && (
          <p className="understand-caution">
            <Icon name="shield" size={15} /> <span><strong>{t('cmdx.caution')}</strong> <MdInline text={u.caution} /></span>
          </p>
        )}
        {concepts.length > 0 && (
          <p className="understand-meta">
            {t('cmdx.concepts')}{' '}
            {concepts.map((c, i) => (
              <span key={c!.id}>
                {i > 0 && ' · '}
                <a href={`/map?concept=${encodeURIComponent(c!.id)}`}>{c!.title}</a>
              </span>
            ))}
          </p>
        )}
        <p className="understand-meta">
          {t('cmdx.checked')}{' '}
          {u.refs.map((r, i) => (
            <span key={r.url}>
              {i > 0 && ' · '}
              <a href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}
