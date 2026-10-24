// Text search for navigation and reference lists; independent of command grading and its CLI model.
/** Search for the palette and reference: every word must appear. */
export function search<T>(items: T[], q: string, text: (x: T) => string): T[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return items
  return items.filter((x) => {
    const s = text(x).toLowerCase()
    return words.every((w) => s.includes(w))
  })
}

/** Like `search`, but best matches first: the whole query in a title, then every word in the title, then elsewhere.
 *  Ties keep the catalogue order (pages and lessons before commands). */
export function searchRanked<T>(items: T[], q: string, title: (x: T) => string, text: (x: T) => string): T[] {
  const query = q.toLowerCase().trim()
  const words = query.split(/\s+/).filter(Boolean)
  if (!words.length) return items
  const scored: { x: T; s: number; i: number }[] = []
  items.forEach((x, i) => {
    const ti = title(x).toLowerCase()
    const all = text(x).toLowerCase()
    if (!words.every((w) => all.includes(w))) return
    const s = ti === query ? 0 : ti.includes(query) ? 1 : words.every((w) => ti.includes(w)) ? 2 : all.includes(query) ? 3 : 4
    scored.push({ x, s, i })
  })
  return scored.sort((a, b) => a.s - b.s || a.i - b.i).map((r) => r.x)
}

/** Plain text from inline Markdown, for one-line descriptions. */
export const plain = (md: string) => md.replace(/\*\*|__|`/g, '').replace(/(^|\W)\*(\S[^*]*\S|\S)\*(?=\W|$)/g, '$1$2').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
