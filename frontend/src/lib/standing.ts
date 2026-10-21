// One reading of the learner's record, used by every page that reports progress: the lesson, the course outline and
// its summary, Review, Progress, the practice lists and the journey map. The store (lib/progress.ts) keeps facts;
// these rules turn them into what a page says, so two pages can never disagree.
//
// Questions (a lesson's Check questions, by stable id; the same ids as `cur.lessons[id].checks`):
//   - a score counts the latest answer: a better attempt replaces a worse one;
//   - a right answer given just after the answer was shown is "corrected": it counts, and pages say how it was reached;
//   - the first attempt stays on record: "right on the first try" is a separate, honestly labelled fact;
//   - only a question whose latest answer is wrong is outstanding (Review's "try again", a lesson summary).
// Activities (labs, incidents, challenges): what completing one means depends on its kind, and is the same everywhere.
import type { Curriculum, ReviewCard } from './data'
import { labStatus, unlocked, type LabProgress, type Progress, type QuestionRecord } from './progress'

export type QuestionState = 'unanswered' | 'wrong' | 'right' | 'corrected'

export function questionState(r?: QuestionRecord): QuestionState {
  if (!r) return 'unanswered'
  if (!r.latest.ok) return 'wrong'
  return r.latest.shown ? 'corrected' : 'right'
}

/** Whether a question counts as right in a score: its latest answer is right (also one corrected after the reveal). */
export const countsRight = (r?: QuestionRecord) => !!r && r.latest.ok

export type ChecksTally = {
  total: number
  answered: number
  /** latest answer right, corrected answers included */
  right: number
  /** of `right`: answered right only after the answer was shown */
  corrected: number
  /** answered right on the first attempt */
  firstTry: number
  /** latest answer wrong: outstanding */
  wrong: string[]
  unanswered: string[]
}

export function tallyChecks(qids: string[], prog: Progress): ChecksTally {
  const t: ChecksTally = { total: qids.length, answered: 0, right: 0, corrected: 0, firstTry: 0, wrong: [], unanswered: [] }
  for (const q of qids) {
    const r = prog.predictions[q]
    const s = questionState(r)
    if (s === 'unanswered') {
      t.unanswered.push(q)
      continue
    }
    t.answered++
    if (r!.first.ok) t.firstTry++
    if (s === 'wrong') t.wrong.push(q)
    else (t.right++, s === 'corrected' && t.corrected++)
  }
  return t
}

/** The Check questions of some lessons, in the order given. */
export const checksOf = (cur: Curriculum, lessonIds: string[]) => lessonIds.flatMap((l) => cur.lessons[l]?.checks || [])

type Kind = Curriculum['labs'][string]['kind']

/** Whether an activity was completed, by what its kind allows: a lab worked through on recordings, an incident
 *  diagnosed (all three debrief self-checks), or any of them verified on a real cluster (a challenge can only be
 *  checked there). Completion is a fact once reached; the status shown next to it (labStatus) is what is true now,
 *  so a later failed live check stays visible. */
export function activityDone(kind: Kind, l?: LabProgress): boolean {
  if (!l) return false
  if (l.verified) return true
  if (kind === 'lab') return !!l.replayed
  if (kind === 'incident') return !!(l.selfCheck?.root && l.selfCheck.evidence && l.selfCheck.fix)
  return false
}

/** Verified on a real cluster, by the latest live verdict. */
export const verifiedNow = (l?: LabProgress) => labStatus(l) === 'verified'

export type ActivityTally = { total: number; done: number; verified: number }

export function tallyActivities(cur: Curriculum, ids: string[], prog: Progress): ActivityTally {
  const labs = ids.map((id) => cur.labs[id]).filter(Boolean)
  return {
    total: labs.length,
    done: labs.filter((l) => activityDone(l.kind, prog.labs[l.id])).length,
    verified: labs.filter((l) => verifiedNow(prog.labs[l.id])).length,
  }
}

/** The recall cards of Review: separate from the lesson checks (a check answered is not a card reviewed). A card joins
 *  the deck when its lesson is finished (or its lab worked on) and is ready at once: `fresh` has never been reviewed,
 *  `again` was reviewed and is due again. Every page that counts cards uses this. */
export function cardQueue(cards: ReviewCard[], prog: Progress, now = Date.now()) {
  const deck = cards.filter((c) => unlocked(c, prog))
  const fresh = deck.filter((c) => !prog.cards[c.id])
  const again = deck.filter((c) => prog.cards[c.id] && prog.cards[c.id].due <= now)
  return { deck, fresh, again, ready: deck.filter((c) => !prog.cards[c.id] || prog.cards[c.id].due <= now) } // in deck order
}
