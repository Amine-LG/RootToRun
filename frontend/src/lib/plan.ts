// A lesson is played as an ordered plan of typed activities with stable ids. The plan is compiled from the lesson's
// content. A lesson written as a teaching flow (`flow`) becomes one activity per step, in the author's order. An
// older long-form lesson: core sections become Learn activities, each Check sits right after the section that teaches
// what it tests (`after`), Predict items sit before the section that answers them, Explore activities hold the
// lesson's diagram or model, Practise holds its labs and host exercises, and a Summary closes the lesson. Nothing is
// inferred from section titles or array positions.
import type { FlowOrder, FlowReflect, FlowShow, FlowTry, Lesson, Predict } from './data'

export type Kind = 'learn' | 'show' | 'try' | 'predict' | 'check' | 'order' | 'reflect' | 'explore' | 'practise' | 'summary'
export type Question = { q: Predict; qid: string }
export type Activity =
  | { id: string; kind: 'learn'; section: Lesson['sections'][number]; minutes: number }
  | { id: string; kind: 'show'; step: FlowShow }
  | { id: string; kind: 'try'; step: FlowTry }
  | { id: string; kind: 'predict'; question: Question; answeredBy: string }
  | { id: string; kind: 'check'; questions: Question[]; anchor: string }
  | { id: string; kind: 'order'; step: FlowOrder }
  | { id: string; kind: 'reflect'; step: FlowReflect }
  | { id: string; kind: 'explore'; diagram?: string; sim?: string; body?: string }
  | { id: string; kind: 'practise'; labs: string[]; host: boolean }
  | { id: string; kind: 'summary' }

const words = (s: string) => s.split(/\s+/).filter(Boolean).length
/** Reading time for one section at ~200 words per minute (technical prose), at least one minute. */
export const readMinutes = (body: string) => Math.max(1, Math.round(words(body) / 200))

export const questionId = (lessonId: string, q: Predict, k: number) => q.id || `lesson:${lessonId}:${k}`

export function compileLesson(l: Lesson): Activity[] {
  if (l.flow?.length) return compileFlow(l)
  const core = l.sections.filter((s) => !s.depth)
  const coreIds = new Set(core.map((s) => s.id))
  const last = core[core.length - 1]?.id
  const qs = l.predict.map((q, k) => ({ q, qid: questionId(l.id, q, k) }))
  // where each question goes: an anchor that is not a core section (missing, or a depth section) falls back to the end
  const placeOf = (q: Predict) => (q.after === 'start' ? 'start' : q.after && coreIds.has(q.after) ? q.after : last)
  const plan: Activity[] = []

  const predictsAt = (anchor: string) =>
    qs.filter(({ q }) => q.role === 'predict' && placeOf(q) === anchor).forEach((question) =>
      plan.push({ id: `predict:${question.qid}`, kind: 'predict', question, answeredBy: question.q.answered_by || '' }),
    )
  const checksAt = (anchor: string) => {
    const here = qs.filter(({ q }) => q.role !== 'predict' && placeOf(q) === anchor)
    if (here.length) plan.push({ id: `check:${anchor}`, kind: 'check', questions: here, anchor })
  }

  predictsAt('start')
  checksAt('start')
  core.forEach((s, i) => {
    plan.push({ id: `learn:${s.id}`, kind: 'learn', section: s, minutes: readMinutes(s.body) })
    predictsAt(s.id)
    checksAt(s.id) // a Check comes right after the section it tests, before anything else
    if (i === 0 && l.diagram) plan.push({ id: `explore:${l.diagram}`, kind: 'explore', diagram: l.diagram })
    if (i === core.length - 1 && l.simulator) plan.push({ id: `explore:${l.simulator}`, kind: 'explore', sim: l.simulator })
  })
  if (l.labs.length || l.commands.length) plan.push({ id: 'practise', kind: 'practise', labs: l.labs, host: l.commands.length > 0 })
  plan.push({ id: 'summary', kind: 'summary' })
  return plan
}

/** A flow lesson: one activity per step. The backend derives one question (`predict` item, `after` = step id) per ask
 * step, so answers keep the same ids and records as in the older format. A diagram or model, if any, comes just
 * before the second titled part; labs come before the summary. Recorded commands appear inside the flow. */
function compileFlow(l: Lesson): Activity[] {
  const plan: Activity[] = []
  const byStep = new Map(l.predict.map((q, k) => [q.after || '', { q, qid: questionId(l.id, q, k) }]))
  let titled = 0
  for (const st of l.flow || []) {
    if (st.kind === 'teach') {
      if (st.title && ++titled === 2 && (l.diagram || l.simulator) && !l.flow?.some((x) => x.kind === 'explore')) plan.push(explore(l))
      plan.push({ id: `learn:${st.id}`, kind: 'learn', section: { id: st.id, title: st.title, body: st.body }, minutes: readMinutes(st.body) })
    } else if (st.kind === 'show') plan.push({ id: `show:${st.id}`, kind: 'show', step: st })
    else if (st.kind === 'try') plan.push({ id: `try:${st.id}`, kind: 'try', step: st })
    else if (st.kind === 'order') plan.push({ id: `order:${st.id}`, kind: 'order', step: st })
    else if (st.kind === 'reflect') plan.push({ id: `reflect:${st.id}`, kind: 'reflect', step: st })
    else if (st.kind === 'explore') plan.push({ id: `explore:${st.id}`, kind: 'explore', sim: st.sim || undefined, diagram: st.diagram || undefined, body: st.body })
    else if (st.kind === 'ask') {
      const question = byStep.get(st.id)
      if (!question) continue
      if (st.guess) plan.push({ id: `predict:${question.qid}`, kind: 'predict', question, answeredBy: question.q.answered_by || '' })
      else plan.push({ id: `check:${st.id}`, kind: 'check', questions: [question], anchor: st.id })
    }
  }
  if ((l.diagram || l.simulator) && !plan.some((a) => a.kind === 'explore')) plan.splice(plan.length, 0, explore(l))
  if (l.labs.length) plan.push({ id: 'practise', kind: 'practise', labs: l.labs, host: false })
  plan.push({ id: 'summary', kind: 'summary' })
  return plan
}

const explore = (l: Lesson): Activity =>
  l.diagram ? { id: `explore:${l.diagram}`, kind: 'explore', diagram: l.diagram } : { id: `explore:${l.simulator}`, kind: 'explore', sim: l.simulator || '' }

/** All graded questions of a lesson, in plan order (used by "Know this already? Answer the checks"). */
export const lessonChecks = (plan: Activity[]): Question[] => plan.flatMap((a) => (a.kind === 'check' ? a.questions : []))

/** Where a question is taught, for "read this part" links after a wrong answer: the section it follows, or in a flow
 * lesson the nearest teaching step before it. */
export function sectionOf(plan: Activity[], anchor: string) {
  const direct = plan.find((a) => a.kind === 'learn' && a.section.id === anchor)
  if (direct) return direct
  const at = plan.findIndex((a) => a.kind === 'check' && a.anchor === anchor)
  for (let i = at - 1; i >= 0; i--) if (plan[i].kind === 'learn') return plan[i]
  return undefined
}
