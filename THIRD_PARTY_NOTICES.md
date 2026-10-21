# Third-party notices

The built website bundles the following third-party works. Their licences apply to those files; the rest of the
project (© 2026 Amine-LG and contributors) is licensed as described in `LICENSE` and `NOTICE` (code, Apache-2.0)
and `content/LICENSE.md` (course content, CC BY-SA 4.0).

| Component | Use | Licence |
|---|---|---|
| React, React DOM and their runtime dependencies (scheduler, loose-envify, js-tokens) | user interface | MIT |
| Figtree (© The Figtree Project Authors), Source Serif 4 (© Adobe, Reserved Font Name "Source"), JetBrains Mono (© The JetBrains Mono Project Authors): variable fonts as distributed by Google Fonts and packaged by Fontsource (per-script subsets in WOFF2), shipped as Fontsource publishes them | fonts | SIL Open Font License 1.1 |
| Shiki 4.5 (`shiki/core`, `@shikijs/*`, the JavaScript regular-expression engine, the YAML and JSON TextMate grammars) and its dependencies (oniguruma-to-es, oniguruma-parser, regex, regex-recursion, regex-utilities, hast-util-to-html and the unified/hast utilities it uses) | code highlighting, loaded only on pages with YAML or JSON code | MIT (one ISC dependency) |

`npm run build` writes **`licenses.txt`** into the built site: the project's own licences and the full licence text of
every production dependency in `frontend/package-lock.json` (`frontend/scripts/licenses.mjs`), so that the notices
travel with the files that need them. The About page links to it.

The local server uses FastAPI, Starlette, Pydantic, Uvicorn, PyYAML and their dependencies (MIT, BSD-3-Clause,
Apache-2.0, PSF-2.0); the optional sign-in code adds PyJWT and cryptography (MIT; Apache-2.0 or BSD-3-Clause).
They are used while building the site and by the local practice tools; neither the static site nor the container
image contains them. Development and test tools (TypeScript, Vite, Vitest, axe-core, Playwright, pytest) are not
distributed with the site.

The container image (`Containerfile`) is based on the official unprivileged nginx image on Alpine Linux: nginx
(BSD-2-Clause) and the Alpine packages it includes, under their own licences as distributed in that base image. The
image adds only the static site above and the nginx configuration in `deploy/nginx/`.

Recorded command outputs come from running open-source and vendor command-line tools on a test cluster; that text
belongs to its owners (see `content/LICENSE.md`). Product names that appear in them are trademarks of their owners.
Examples adapted from other projects' documentation are credited, with their licences, in `content/ATTRIBUTIONS.md`.

The screenshots of the OpenShift web console in `content/media/` are captures of the console of OpenShift Local, shown
as captured except that the cluster's identifier is blurred where it appears. The interface they show belongs to its
owners, and the Red Hat and OpenShift names, logos and artwork in them are trademarks of Red Hat, LLC. They are not
covered by the project's licences and are not relicensed by the project; only the captions and descriptions written
for them are (see `content/LICENSE.md`).
