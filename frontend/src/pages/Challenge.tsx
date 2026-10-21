// A challenge states outcomes, not steps. The learner reaches them their own way on a real cluster; the grader reads
// the cluster's actual state and behaviour (connections, effective permissions, readiness) and reports each
// requirement separately. Without a cluster the page is honest about what it can offer: the brief, hints, the
// recorded evidence that the grader works, and the reference solution after the learner asks for it.
import { useEffect, useMemo, useRef, useState } from 'react'
import { CommandBlock } from '../components/Term'
import { CodeBlock } from '../components/Code'
import { toast } from '../components/Toast'
import { fmtDate, Icon, Refs } from '../components/ui'
import { api, type LabData, type Reveal, type Verification } from '../lib/data'
import { useApp } from '../lib/app'
import { t } from '../lib/i18n'
import { Md, MdInline } from '../lib/md'
import { labUpdate, useProgress, XP } from '../lib/progress'
import { reveal as revealView } from '../lib/reveal'
import { Checks, entryIndex, Environment, HintBox, RestartAttempt, TerminalDrawer, useAttemptGuard } from './Lab'
import '../practice.css'

export default function ChallengeRun({ data, onRestart }: { data: LabData; onRestart: () => void }) {
  const { lab, recording: rec } = data
  const { lang, live, meta } = useApp()
  const prog = useProgress()
  const lp = prog.labs[lab.id]
  const current = useAttemptGuard(lab.id)
  const [hints, setHints] = useState<string[]>([])
  const [answer, setAnswer] = useState<Reveal | null>(null)
  const [grade, setGrade] = useState<Verification | null>(null)
  const answerBox = useRef<HTMLDivElement>(null)
  const find = useMemo(() => entryIndex(rec, answer?.fix_recording || []), [rec, answer])
  // the current attempt (lib/progress.ts IncidentState): hints and solution shown in it; older records have no
  // attempt, and then everything used so far is shown, as before
  const shownHints = lp?.incident ? lp.incident.hints || 0 : lp?.hints || 0
  const solutionShown = lp?.incident ? lp.incident.stage === 1 : !!(lp?.revealed || lp?.verified)
  useEffect(() => {
    if (shownHints) api.hints(lab.id, shownHints, lang).then(setHints, () => 0)
    if (solutionShown) api.reveal(lab.id, lang).then(setAnswer, () => 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lab.id, lang])

  async function moreHint() {
    const n = hints.length + 1
    labUpdate(lab.id, (l) => {
      l.hints = Math.max(l.hints || 0, n)
      if (l.incident) l.incident = { ...l.incident, hints: n }
    })
    const h = await api.hints(lab.id, n, lang)
    if (current()) setHints(h)
  }
  async function showAnswer() {
    const r = await api.reveal(lab.id, lang)
    if (!current()) return // restarted (or left) while the answer was on its way
    setAnswer(r)
    labUpdate(lab.id, (l) => {
      l.revealed = l.revealed || Date.now()
      if (l.incident) l.incident = { ...l.incident, stage: 1 }
    })
    revealView(answerBox.current)
  }
  function onGraded(v: Verification) {
    setGrade(v)
    const first = v.verdict === 'verified' && !lp?.verified
    if (first) toast(t('toast.verified'), t('toast.verifiedNote'), 'ok', true)
    labUpdate(lab.id, (l) => {
      const now = Date.now()
      l.verdict = v.verdict
      l.verdictAt = now
      if (v.verdict === 'verified') l.verified = now
    }, first ? (lp?.revealed ? XP.labVerified : XP.incidentSolved) : 0)
  }
  const trials = answer?.trials || rec?.trials || []
  const byId = Object.fromEntries((grade?.results || []).map((r) => [r.id, r]))

  return (
    <>
      <section className="lesson-step ch-brief" aria-labelledby="ch-situation">
        <h2 className="step-h2" id="ch-situation">{t('ch.situation')}</h2>
        <Md text={lab.symptom} />
        {lab.background && (
          <details className="more" data-testid="activity-background">
            <summary>{t('lab.whatRunsHere')}</summary>
            <Md text={lab.background} />
          </details>
        )}
        {Object.keys(lab.files).length > 0 && (
          <details className="more" data-testid="challenge-files">
            <summary>{t('lab.files', { n: Object.keys(lab.files).length })}</summary>
            {Object.entries(lab.files).map(([path, body]) => (
              <div key={path}>
                <div className="file-name mono">lab/{path}</div>
                <CodeBlock code={body} caption={`lab/${path}`} label={t('lesson.copySource', { name: `lab/${path}` })} />
              </div>
            ))}
          </details>
        )}
        <h2 className="step-h2 ch-req-h">{t('ch.requirements')}</h2>
        <p className="muted small">{t('ch.requirementsNote')}</p>
        <ol className="ch-reqs" data-testid="requirements">
          {(lab.requirements || []).map((r, i) => (
            <li key={i}>
              <span className="ch-req-t">
                <MdInline text={r} />
              </span>
            </li>
          ))}
        </ol>
        <details className="more">
          <summary>{t('ch.howGraded', { n: lab.checks.length })}</summary>
          <ul className="small ch-criteria">
            {lab.checks.map((c) => (
              <li key={c.id}>
                {byId[c.id] && <Icon name={byId[c.id].status === 'pass' ? 'check' : byId[c.id].status === 'error' ? 'info' : 'x'} size={13} />} {c.title}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section className="ch-work" aria-labelledby="ch-work">
        <h2 className="ch-h" id="ch-work">{t('ch.workTitle')}</h2>
        {meta?.mode === 'cluster' && <Environment lab={lab} onVerified={onGraded} />}
        {live ? (
          <>
            <p className="muted small">{t('ch.liveHow')}</p>
            <TerminalDrawer lab={lab} />
          </>
        ) : (
          <p className="callout ch-nocluster" role="note">
            <strong>{t('ch.noClusterTitle')}</strong> {t('ch.noClusterText')} <a href="/about#own-cluster">{t('env.ownCluster')}</a>
          </p>
        )}
        <HintBox hints={hints} total={lab.hint_count} onMore={moreHint} />
        <RestartAttempt labId={lab.id} kind="challenge" begun={hints.length > 0 || !!answer || !!grade} onRestart={onRestart} />
      </section>

      <section className="ch-answer" ref={answerBox}>
        {!answer ? (
          <div className="ch-reveal">
            <button className="btn ghost" onClick={showAnswer} data-testid="reveal">
              <Icon name="eye" size={15} /> {t('ch.showSolution')}
            </button>
            <span className="muted small">{t('ch.showSolutionNote')}</span>
          </div>
        ) : (
          <div className="ch-solution">
            <h2 className="ch-h">{t('ch.solution')}</h2>
            <p className="muted small">{answer.verify_after && answer.fix.some((c) => find('fix', c)) ? t('ch.solutionNote') : t('ch.solutionNoteUnrecorded')}</p>
            {answer.fix.map((c, i) => (
              <CommandBlock key={i} c={c} entry={find('fix', c)} />
            ))}
            {answer.verify_after && <Checks v={answer.verify_after} title={t('ch.afterSolution')} />}
            <h3>{t('ch.whyItWorks')}</h3>
            <Md text={answer.root_cause} />
            {answer.alternatives && (
              <>
                <h3>{t('inc.alternatives')}</h3>
                <Md text={answer.alternatives} />
              </>
            )}
            {answer.sre && (
              <details className="more">
                <summary>{t('ch.inReview')}</summary>
                <Md text={answer.sre} />
              </details>
            )}
            {lab.questions.length > 0 && (
              <details className="more" data-testid="challenge-questions">
                <summary>{t('lab.questions')}</summary>
                <div className="qa">
                  {lab.questions.map((q, i) => (
                    <details key={i}>
                      <summary>
                        <Md text={q.q} />
                      </summary>
                      <Md text={q.a} />
                    </details>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </section>

      {rec && (
        <details className="more ch-evidence">
          <summary>{t('ch.graderEvidence')}</summary>
          <p className="muted small">
            {rec.ok
              ? t('ch.graderEvidenceText', { v: rec.cluster.openshift || '?', date: fmtDate(rec.recorded_at) })
              : t('ch.graderEvidenceBad')}
          </p>
          {rec.verify_before && <Checks v={rec.verify_before} title={t('ch.startState')} />}
          {trials.length > 0 && (
            <table className="ch-trials">
              <caption className="sr-only">{t('ch.trialsCaption')}</caption>
              <thead>
                <tr>
                  <th scope="col">{t('ch.trialAttempt')}</th>
                  <th scope="col">{t('ch.trialExpected')}</th>
                  <th scope="col">{t('ch.trialGraded')}</th>
                </tr>
              </thead>
              <tbody>
                {trials.map((tr, i) => (
                  <tr key={tr.id} className={tr.ok ? 'ok' : 'bad'}>
                    <td>
                      <span className={`pill ${tr.kind === 'alternative' ? 'ok' : 'warn'}`}>{t(`ch.kind.${tr.kind}` as 'ch.kind.wrong')}</span> {tr.title || t('ch.recordedAttempt', { n: i + 1 })}
                    </td>
                    <td>{t(`verdict.${tr.expect}` as 'verdict.verified')}</td>
                    <td>
                      <Icon name={tr.ok ? 'check' : 'x'} size={13} /> {t(`verdict.${tr.got}` as 'verdict.verified')}
                      {!tr.ok && <div className="small">{tr.expect === tr.got ? t('ch.trialMismatch') : t('ch.trialWrongGrade')}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </details>
      )}
      {lab.references.length > 0 && <Refs refs={lab.references} />}
    </>
  )
}
