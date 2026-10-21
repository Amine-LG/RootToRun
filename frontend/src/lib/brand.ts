// The product identity, defined once in frontend/product.json. The app (header, titles, footer), index.html (through
// vite.config.ts) and the server and static export (backend/academy/config.py SITE_NAME) all read it from there. A fork
// that renames the project changes product.json, the mark in components/Shell.tsx (Logo), frontend/public/favicon.svg
// and the README title, and keeps the licence notices (LICENSE, NOTICE, content/LICENSE.md). "OpenShift" and
// "Red Hat" are descriptive references to the technology and never part of the name.
import product from '../../product.json'

export const BRAND = product.name
export const BRAND_LINE1 = product.name
export const BRAND_LINE2 = product.nameLine2
export const CREATOR = product.creator
export const COPYRIGHT = product.copyright
