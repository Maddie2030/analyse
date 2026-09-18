#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS="$ROOT/deploy/docker-desktop-hybrid/user-apps.yaml"
QUOTA="$ROOT/deploy/docker-desktop-hybrid/resource-guardrails-user.yaml"
HPA="$ROOT/deploy/docker-desktop-hybrid/user-hpa.yaml"
KEDA="$ROOT/deploy/docker-desktop-hybrid/user-keda.yaml"

mi() {
  local v="${1//\"/}"; v="${v//\'/}"
  case "$v" in
    *Gi) awk -v n="${v%Gi}" 'BEGIN{printf "%d\n", n*1024}' ;;
    *Mi) printf '%d\n' "${v%Mi}" ;;
    *) echo "unsupported memory quantity: $1" >&2; return 2 ;;
  esac
}

declare -A base req lim targetmax
while read -r name rep r l; do
  [[ -n "$name" ]] || continue
  base["$name"]="$rep"; req["$name"]="$r"; lim["$name"]="$l"; targetmax["$name"]="$rep"
done < <(awk '
function mi(s){gsub(/["\047]/,"",s); if(s~/Gi$/){sub(/Gi$/,"",s); return int((s+0)*1024)} if(s~/Mi$/){sub(/Mi$/,"",s); return int(s+0)} print "unsupported memory quantity: "s > "/dev/stderr"; exit 2}
function flush(){if(kind=="Deployment"&&name!=""){if(rep=="")rep=1;print name,rep,req+0,lim+0}kind=name=rep="";req=lim=0;section="";inmeta=0}
/^---[[:space:]]*$/ {flush();next}
/^kind:[[:space:]]*/ {kind=$2;next}
/^metadata:[[:space:]]*$/ {inmeta=1;next}
inmeta&&/^  name:[[:space:]]*/ {name=$2;inmeta=0;next}
/^  replicas:[[:space:]]*/ {rep=$2;next}
/^          requests:[[:space:]]*$/ {section="req";next}
/^          limits:[[:space:]]*$/ {section="lim";next}
/^            memory:[[:space:]]*/ {v=$2;if(section=="req")req+=mi(v);else if(section=="lim")lim+=mi(v);next}
END{flush()}
' "$APPS")

# autoscaling/v2 HPA maxReplicas
while read -r name max; do
  [[ -n "$name" ]] || continue
  [[ -n "${targetmax[$name]+x}" ]] || { echo "HPA target missing deployment: $name" >&2; exit 1; }
  (( max > targetmax[$name] )) && targetmax[$name]="$max"
done < <(awk '
function flush(){if(kind=="HorizontalPodAutoscaler"&&target!="")print target,max+0;kind=target=max="";inscale=0}
/^---[[:space:]]*$/ {flush();next}
/^kind:[[:space:]]*/ {kind=$2;next}
/^  scaleTargetRef:[[:space:]]*$/ {inscale=1;next}
inscale&&/^    name:[[:space:]]*/ {target=$2;inscale=0;next}
/^  maxReplicas:[[:space:]]*/ {max=$2;next}
END{flush()}
' "$HPA")

# KEDA maxReplicaCount is also a total target replica count, not an addition.
while read -r name max; do
  [[ -n "$name" ]] || continue
  [[ -n "${targetmax[$name]+x}" ]] || { echo "KEDA target missing deployment: $name" >&2; exit 1; }
  (( max > targetmax[$name] )) && targetmax[$name]="$max"
done < <(awk '
function flush(){if(kind=="ScaledObject"&&target!="")print target,max+0;kind=target=max="";inscale=0}
/^---[[:space:]]*$/ {flush();next}
/^kind:[[:space:]]*/ {kind=$2;next}
/^  scaleTargetRef:[[:space:]]*$/ {inscale=1;next}
inscale&&/^    name:[[:space:]]*/ {target=$2;inscale=0;next}
/^  maxReplicaCount:[[:space:]]*/ {max=$2;next}
END{flush()}
' "$KEDA")

q_lim="$(mi "$(awk '/^[[:space:]]+limits\.memory:/ {print $2;exit}' "$QUOTA")")"
q_req="$(mi "$(awk '/^[[:space:]]+requests\.memory:/ {print $2;exit}' "$QUOTA")")"
total_lim=0; total_req=0
for name in "${!targetmax[@]}"; do
  total_lim=$((total_lim + targetmax[$name] * lim[$name]))
  total_req=$((total_req + targetmax[$name] * req[$name]))
done
(( total_lim <= q_lim )) || { echo "user autoscaler maxima exceed limits.memory quota: ${total_lim}Mi > ${q_lim}Mi" >&2; exit 1; }
(( total_req <= q_req )) || { echo "user autoscaler maxima exceed requests.memory quota: ${total_req}Mi > ${q_req}Mi" >&2; exit 1; }
# Preserve a little admission headroom; don't tune the maxima to the exact byte.
(( q_lim - total_lim >= 128 )) || { echo "user limits quota headroom too small: $((q_lim-total_lim))Mi" >&2; exit 1; }
printf 'user-plane max autoscaling budget PASSED: limits=%sMi/%sMi requests=%sMi/%sMi headroom=%sMi\n' \
  "$total_lim" "$q_lim" "$total_req" "$q_req" "$((q_lim-total_lim))"
