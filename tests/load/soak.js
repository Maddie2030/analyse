import { Counter, Rate, Trend } from 'k6/metrics';
import { setupWorkload, runWorkload, isConnectionWorkload } from './workload-common.js';

const WORKLOAD = __ENV.K6_BREAKPOINT_WORKLOAD || 'catalog_detail';
const LEVEL = Math.max(1, Number(__ENV.K6_SOAK_LEVEL || '10'));
const DURATION_SECONDS = Math.max(60, Number(__ENV.K6_SOAK_DURATION_SECONDS || '600'));
const P95_SLO = Math.max(1, Number(__ENV.K6_BREAKPOINT_P95_MS || '700'));
const P99_SLO = Math.max(P95_SLO, Number(__ENV.K6_BREAKPOINT_P99_MS || '1500'));
const MAX_VUS = Math.max(100, Number(__ENV.K6_SOAK_MAX_VUS || String(Math.min(1500, Math.max(100, LEVEL * 6)))));
const isConnections = isConnectionWorkload(WORKLOAD);
const latency = new Trend('mreader_soak_latency', true);
const failures = new Rate('mreader_soak_failures');
const requests = new Counter('mreader_soak_requests');
const serverErrors = new Rate('mreader_soak_server_errors');

export const options = isConnections ? {
  scenarios: { soak: { executor:'constant-vus', vus:LEVEL, duration:`${DURATION_SECONDS}s`, exec:'run' } }, thresholds:{},
} : {
  scenarios: { soak: { executor:'constant-arrival-rate', rate:LEVEL, timeUnit:'1s', duration:`${DURATION_SECONDS}s`, preAllocatedVUs:Math.min(MAX_VUS,Math.max(20,LEVEL*2)), maxVUs:MAX_VUS, exec:'run' } }, thresholds:{},
};
export function setup(){ return setupWorkload(WORKLOAD); }
function observe(event){ requests.add(1); failures.add(!event.ok); serverErrors.add(Number(event.status||0)>=500); latency.add(event.type==='ws'?event.duration:event.res.timings.duration); }
export function run(data){ runWorkload(WORKLOAD,data,observe,'soak',isConnections?5:2); }
function values(data,name){ return (data.metrics[name]&&data.metrics[name].values)||{}; }
function num(v){ return Number.isFinite(Number(v))?Number(v):0; }
export function handleSummary(data){
  const lat=values(data,'mreader_soak_latency'), fail=values(data,'mreader_soak_failures'), req=values(data,'mreader_soak_requests'), err=values(data,'mreader_soak_server_errors');
  const count=num(req.count), p50=num(lat['p(50)']), p95=num(lat['p(95)']), p99=num(lat['p(99)']), failure=num(fail.rate), server=num(err.rate);
  const state=count>0 && failure<0.01 && server<0.005 && p95<=P95_SLO && p99<=P99_SLO ? 'PASS':'FAIL';
  return { stdout:`\nMREADER_SOAK_RESULT=${[WORKLOAD,LEVEL,isConnections?'connections':'rps',DURATION_SECONDS,count,p50.toFixed(2),p95.toFixed(2),p99.toFixed(2),failure.toFixed(6),server.toFixed(6),state].join('|')}\n` };
}
