#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bad=0
while IFS= read -r file; do
  awk -v file="$file" '
    BEGIN{allowed=" FROM RUN COPY ADD CMD ENTRYPOINT WORKDIR ENV ARG LABEL EXPOSE VOLUME USER HEALTHCHECK STOPSIGNAL ONBUILD SHELL MAINTAINER "}
    {
      raw=$0; s=raw; sub(/^[[:space:]]+/,"",s); sub(/[[:space:]]+$/,"",s)
      if(s==""||s~/^#/)next
      if(cont){cont=(s~/\\$/); next}
      split(s,a,/[[:space:]]+/); tok=toupper(a[1])
      if(index(allowed," " tok " ")==0){print file ":" NR ": unexpected top-level Dockerfile token " tok ": " s > "/dev/stderr"; bad=1}
      cont=(s~/\\$/)
    }
    END{if(bad)exit 1}
  ' "$file" || bad=1
done < <(find "$ROOT" -type f -name 'Dockerfile*' -print | sort)
(( bad == 0 )) || exit 1

# Guard the Image Service regression that shipped a bare `python -m pip ...`
# line without RUN. This refers to Python inside the pinned service image, not host Python.
grep -Fq 'RUN python -m pip install --prefix=/install -r requirements.txt' "$ROOT/services/image_service/Dockerfile"

echo 'dockerfile static regression PASSED'
