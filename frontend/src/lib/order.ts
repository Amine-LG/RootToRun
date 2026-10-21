// The order in which a question's choices are shown. Authors tend to put the right answer in the same place
// (an independent review found 87% of keyed answers in second position), which lets a learner score without
// knowing anything. Each question gets its own stable shuffle, derived from its id: the same for every visit and
// every learner, so feedback, saved answers and screenshots stay consistent. Stored picks always use the
// original (authored) index; only the display order changes.
export function displayOrder(key: string, n: number): number[] {
  let h = 2166136261
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 16777619) >>> 0
  }
  const a = Array.from({ length: n }, (_, i) => i)
  for (let i = n - 1; i > 0; i--) {
    h ^= h >>> 15
    h = Math.imul(h, 2246822507) >>> 0
    h ^= h >>> 13
    h = Math.imul(h, 3266489909) >>> 0
    h ^= h >>> 16
    h >>>= 0
    const j = h % (i + 1)
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}
