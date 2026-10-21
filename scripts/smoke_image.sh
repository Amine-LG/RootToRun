#!/usr/bin/env bash
# Smoke test of the production image, run by CI and by the release before it publishes the image it tested.
#   scripts/smoke_image.sh <image> [port]
# Starts the image as it is deployed (read-only root, no capabilities, no privilege escalation, bound to 127.0.0.1),
# checks routes, redirects, errors and headers, checks that nothing but nginx and static files is inside, and leaves
# the container running as "site-smoke" for the browser tests. Uses CONTAINER_ENGINE, else docker, else podman.
set -euo pipefail
image=$1
port=${2:-8080}
base=http://127.0.0.1:$port
engine=${CONTAINER_ENGINE:-$(command -v docker || command -v podman)}

"$engine" rm -f site-smoke > /dev/null 2>&1 || true
"$engine" run -d --name site-smoke -p "127.0.0.1:$port:8080" --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges "$image" > /dev/null
trap 'status=$?; [ "$status" = 0 ] || "$engine" logs site-smoke 2>&1 | tail -50' EXIT
for _ in $(seq 30); do
  if curl -fsS --max-time 2 "$base/healthz" > /dev/null 2>&1; then break; fi
  sleep 1
done

expect() {  # expect <status> <path> [method]
  status=$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' -X "${3:-GET}" "$base$2")
  if [ "$status" != "$1" ]; then echo "expected $1 for ${3:-GET} $2, got $status" >&2; exit 1; fi
}
expect 200 /healthz
expect 200 /
expect 200 /learn/linux
expect 200 /data/meta.json
expect 200 /version.json
expect 200 /licenses.txt
expect 301 /learn/linux/
expect 301 /lesson/lx.first-steps
expect 404 /__missing_page__
expect 404 /api/meta
expect 404 /%5Cevil.example/   # never a redirect to another site
expect 405 / POST

# the protective headers, with their values, on pages, redirects, errors and refused methods alike
csp="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
for req in "GET /learn/linux" "GET /learn/linux/" "GET /lesson/lx.first-steps" "GET /__missing_page__" "GET /api/meta" "POST /"; do
  headers=$(curl -sS --max-time 5 -o /dev/null -D - -X "${req% *}" "$base${req#* }" | tr -d '\r')
  for want in "content-security-policy: $csp" "x-content-type-options: nosniff" "x-frame-options: DENY" \
              "referrer-policy: strict-origin-when-cross-origin" "cross-origin-resource-policy: same-origin"; do
    grep -qixF "$want" <<< "$headers" || { echo "$req: expected header '$want'" >&2; exit 1; }
  done
done
headers=$(curl -sSI --max-time 5 "$base/learn/linux" | tr -d '\r')
grep -qix 'cache-control: no-cache' <<< "$headers" || { echo "pages must be revalidated" >&2; exit 1; }
# redirects go to the exact current address on this site, query kept
location() { curl -sS --max-time 5 -o /dev/null -w '%{redirect_url}' "$base$1"; }  # absolute, compared literally
[ "$(location '/lesson/lx.first-steps?ref=a&b=1')" = "$base/learn/linux/your-first-minutes-in-a-shell?ref=a&b=1" ] || { echo "old address: wrong redirect target" >&2; exit 1; }
[ "$(location '/learn/linux/')" = "$base/learn/linux" ] || { echo "trailing slash: wrong redirect target" >&2; exit 1; }
asset=$(curl -sS --max-time 5 "$base/" | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1)
curl -sSI --max-time 5 "$base$asset" | grep -qi '^cache-control: .*immutable' || { echo "assets must be immutable" >&2; exit 1; }

uid=$("$engine" exec site-smoke id -u)
[[ "$uid" =~ ^[0-9]+$ && "$uid" != 0 ]] || { echo "the image must run as a non-root user (uid: '$uid')" >&2; exit 1; }
# shellcheck disable=SC2016 # the script runs inside the container
"$engine" exec site-smoke sh -ec '
  for binary in python python3 uvicorn node npm oc kubectl curl; do
    if command -v "$binary" > /dev/null 2>&1; then echo "unexpected program in the image: $binary" >&2; exit 1; fi
  done
  # every directory a program or configuration could hide in; find must read them all, or the check fails
  found=$(find /bin /sbin /usr /lib /etc /opt /home /srv /var \( -name "*.py" -o -name "*kubeconfig*" -o -name ".env" \))
  if printf "%s\n" "$found" | grep -v "^/srv/site/" | grep -q .; then
    echo "unexpected file in the image:" >&2; printf "%s\n" "$found" | grep -v "^/srv/site/" >&2; exit 1
  fi
'
echo "smoke test passed: $image"
