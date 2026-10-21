// UI strings. Content (lessons, labs) is translated on the server side under content/<lang>/;
// this catalog covers the interface. Add a language: copy i18n/en.ts to i18n/<lang>.ts, translate,
// register it below, and add content/<lang>/.
import { useSyncExternalStore } from 'react'
import en from '../i18n/en'

export type Catalog = typeof en
const catalogs: Record<string, Partial<Catalog>> = { en }
export const LANG_NAMES: Record<string, string> = { en: 'English', fr: 'Français' }

let lang = (() => {
  try {
    return localStorage.getItem('osa.lang') || 'en'
  } catch {
    return 'en'
  }
})()
const subs = new Set<() => void>()

export function setLang(l: string) {
  lang = l
  try {
    localStorage.setItem('osa.lang', l)
  } catch {
    /* private mode */
  }
  document.documentElement.lang = l
  subs.forEach((f) => f())
}
export const getLang = () => lang

export function useLang() {
  return useSyncExternalStore(
    (f) => {
      subs.add(f)
      return () => subs.delete(f)
    },
    () => lang,
  )
}

type Key = keyof Catalog
/** t('home.title') or t('lab.steps', {n: 3}) with {n} placeholders. Falls back to English. */
export function t(key: Key, vars?: Record<string, string | number>): string {
  let s = (catalogs[lang]?.[key] ?? en[key] ?? key) as string
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}
