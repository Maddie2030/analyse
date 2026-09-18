# Input: timestamp<TAB>namespace<TAB>pod<TAB>memory (kubectl top units).
function mib(v, n) {
  n=v; sub(/Ki$/, "", n); if (v ~ /Ki$/) return n/1024;
  n=v; sub(/Mi$/, "", n); if (v ~ /Mi$/) return n+0;
  n=v; sub(/Gi$/, "", n); if (v ~ /Gi$/) return (n+0)*1024;
  n=v; sub(/Ti$/, "", n); if (v ~ /Ti$/) return (n+0)*1048576;
  n=v; sub(/K$/, "", n); if (v ~ /K$/) return n/1000/1024/1024;
  n=v; sub(/M$/, "", n); if (v ~ /M$/) return n/1000/1000*0.953674;
  return n/1024/1024;
}
NF >= 4 {
  key=$2 "/" $3; value=mib($4);
  if (!(key in first)) first[key]=value;
  last[key]=value; count[key]++;
}
END {
  samples=0; failures=0;
  for (key in count) {
    samples += count[key];
    delta=last[key]-first[key]; ratio=(first[key] > 0 ? last[key]/first[key] : 1);
    if (count[key] >= 3 && delta > 128 && ratio > 2.5) {
      printf("FAIL\t%s\tfirst_mib=%.2f\tlast_mib=%.2f\tdelta_mib=%.2f\tratio=%.2f\tsamples=%d\n", key, first[key], last[key], delta, ratio, count[key]);
      failures++;
    }
  }
  if (samples == 0) { print "SKIP\tmetrics-server data unavailable"; exit 0; }
  if (failures == 0) print "PASS\tno same-pod gross memory growth (>128Mi and >2.5x)";
  exit(failures ? 1 : 0);
}
