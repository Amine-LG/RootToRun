# The public website: static files served by an unprivileged nginx. Node and Python are used only while building
# (the frontend build, then the static export that validates the content and writes one page per address); the final
# image holds nginx, its configuration and the exported files, nothing else: no Python, no academy server, no cluster
# client, no credentials.
#   podman build -t localhost/static-site:dev --build-arg BUILD_COMMIT=$(git rev-parse HEAD) .
#   podman run --rm -p 127.0.0.1:8080:8080 --read-only --tmpfs /tmp --cap-drop ALL localhost/static-site:dev
# The local practice server (./run.sh, scripts/practice-server.sh) is a different thing and is never in this image.
# Base images are pinned by digest (multi-architecture index); update the digest and the tag comment together.

# 1. The frontend.
FROM docker.io/library/node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY LICENSE NOTICE /src/
RUN npm run build

# 2. The static export: content checks, one page per address, data/*.json, the nginx redirect map, then the checks
#    of the result (links and assets, credentials, course codes). Any failure stops the build.
FROM docker.io/library/python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS export
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY requirements.txt ./
RUN pip install --no-compile -r requirements.txt
COPY backend/ backend/
COPY content/ content/
COPY scripts/export_static.py scripts/public_scan.py scripts/check_site.py scripts/
COPY frontend/package.json frontend/product.json frontend/
COPY --from=web /src/frontend/dist /site
# BUILD_COMMIT: the full commit (there is no .git here), shown on the About page and in version.json.
# SITE_URL: the public address (canonical links and sitemap.xml). REPO_URL: the public repository ("Edit this lesson").
ARG BUILD_COMMIT=""
ARG SITE_URL=""
ARG REPO_URL=""
RUN ACADEMY_BUILD_COMMIT="$BUILD_COMMIT" ACADEMY_REPO_URL="$REPO_URL" \
      python scripts/export_static.py --out /site --site-url "$SITE_URL" --redirect-map /redirects.map \
 && rm /site/studio-ids.json \
 && python scripts/check_site.py /site \
 && python scripts/public_scan.py /site

# 3. The runtime: nginx only (the slim variant: no curl, no extra modules), as a non-root user (UID 101 in this image;
#    any UID works, the files are world-readable). The site has its own directory, so the image's sample pages are
#    never served.
FROM docker.io/nginxinc/nginx-unprivileged:stable-alpine-slim@sha256:4ac59c85c8c46d9e91eaabd2122cda4923ba380cf11f4138e389f069bcdc77a3
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=export /redirects.map /etc/nginx/redirects.map
COPY --from=export /site /srv/site
EXPOSE 8080
# nginx itself, without the image's start-up scripts (they rewrite files under /etc/nginx, which is read-only here)
ENTRYPOINT ["nginx", "-g", "daemon off;"]
