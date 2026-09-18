#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS="$ROOT/deploy/docker-desktop-hybrid/admin-apps.yaml"
QUOTA="$ROOT/deploy/docker-desktop-hybrid/resource-guardrails-admin.yaml"
KEDA="$ROOT/deploy/docker-desktop-hybrid/admin-keda.yaml"

mi() {
  local v="${1//\"/}"
  v="${v//\'/}"
  case "$v" in
    *Gi) awk -v n="${v%Gi}" 'BEGIN{printf "%d\n", n*1024}' ;;
    *Mi) printf '%d\n' "${v%Mi}" ;;
    *) echo "unsupported memory quantity: $1" >&2; return 2 ;;
  esac
}

declare -A replicas requests limits maxrep
while read -r name rep req lim; do
  [[ -n "$name" ]] || continue
  replicas["$name"]="$rep"
  requests["$name"]="$req"
  limits["$name"]="$lim"
done < <(awk '
function mi(s){gsub(/["\047]/,"",s); if(s~/Gi$/){sub(/Gi$/,"",s); return int((s+0)*1024)} if(s~/Mi$/){sub(/Mi$/,"",s); return int(s+0)} print "unsupported memory quantity: "s > "/dev/stderr"; exit 2}
function flush(){ if(kind=="Deployment" && name!=""){ if(rep=="") rep=1; print name,rep,req+0,lim+0 } kind=name=rep=""; req=lim=0; section=""; inmeta=0 }
/^---[[:space:]]*$/ {flush(); next}
/^kind:[[:space:]]*/ {kind=$2; next}
/^metadata:[[:space:]]*$/ {inmeta=1; next}
inmeta && /^  name:[[:space:]]*/ {name=$2; inmeta=0; next}
/^  replicas:[[:space:]]*/ {rep=$2; next}
/^          requests:[[:space:]]*$/ {section="req"; next}
/^          limits:[[:space:]]*$/ {section="lim"; next}
/^            memory:[[:space:]]*/ {v=$2; if(section=="req")req+=mi(v); else if(section=="lim")lim+=mi(v); next}
END{flush()}
' "$APPS")

while read -r name max; do
  [[ -n "$name" ]] || continue
  maxrep["$name"]="$max"
done < <(awk '
function flush(){if(kind=="ScaledObject"&&name!="")print name,max+0;kind=name=max="";inmeta=0}
/^---[[:space:]]*$/ {flush();next}
/^kind:[[:space:]]*/{kind=$2;next}
/^metadata:[[:space:]]*$/{inmeta=1;next}
inmeta&&/^  name:[[:space:]]*/{name=$2;inmeta=0;next}
/^  maxReplicaCount:[[:space:]]*/{max=$2;next}
END{flush()}
' "$KEDA")

q_lim_raw="$(awk '/^[[:space:]]+limits\.memory:/ {print $2; exit}' "$QUOTA")"
q_req_raw="$(awk '/^[[:space:]]+requests\.memory:/ {print $2; exit}' "$QUOTA")"
q_lim="$(mi "$q_lim_raw")"
q_req="$(mi "$q_req_raw")"

base_lim=0
base_req=0
for n in "${!replicas[@]}"; do
  base_lim=$((base_lim + replicas[$n] * limits[$n]))
  base_req=$((base_req + replicas[$n] * requests[$n]))
done

check_scenario() {
  local label="$1"; shift
  local lim="$base_lim" req="$base_req" item name count
  for item in "$@"; do
    name="${item%%=*}"; count="${item#*=}"
    [[ -n "${maxrep[$name]+x}" ]] || { echo "$label: $name is not a KEDA target" >&2; exit 1; }
    (( count <= maxrep[$name] )) || { echo "$label: asks $count $name, max is ${maxrep[$name]}" >&2; exit 1; }
    lim=$((lim + limits[$name] * count))
    req=$((req + requests[$name] * count))
  done
  (( lim <= q_lim )) || { echo "$label: memory limits ${lim}Mi exceed admin quota ${q_lim}Mi" >&2; exit 1; }
  (( req <= q_req )) || { echo "$label: memory requests ${req}Mi exceed admin quota ${q_req}Mi" >&2; exit 1; }
  echo "PASS $label: limits=${lim}Mi/${q_lim}Mi requests=${req}Mi/${q_req}Mi"
}

check_scenario two-series-workers scraper-series-worker=2
check_scenario two-batch-workers scraper-batch-worker=2
check_scenario two-series-plus-media scraper-series-worker=2 media-worker=1
check_scenario one-each-plus-thumbnail scraper-series-worker=1 scraper-batch-worker=1 media-worker=1 media-thumbnail-worker=1

(( limits[scraper-series-worker] <= 768 )) || { echo "scraper-series-worker limit too high: ${limits[scraper-series-worker]}Mi" >&2; exit 1; }
(( limits[media-worker] <= 1536 )) || { echo "media-worker limit too high: ${limits[media-worker]}Mi" >&2; exit 1; }

echo 'twin-plane resource budget regression PASSED'
