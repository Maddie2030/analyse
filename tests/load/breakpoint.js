import { Counter, Rate, Trend } from 'k6/metrics';
import { setupWorkload, runWorkload, isConnectionWorkload } from './workload-common.js';

const WORKLOAD = __ENV.K6_BREAKPOINT_WORKLOAD || 'catalog_detail';
const LEVEL = Math.max(1, Number(__ENV.K6_BREAKPOINT_LEVEL || '1'));
const DURATION_SECONDS = Math.max(5, Number(__ENV.K6_BREAKPOINT_DURATION_SECONDS || '30'));
const MAX_VUS = Math.max(20, Number(__ENV.K6_BREAKPOINT_MAX_VUS || String(Math.max(100, LEVEL * 4))));
const P95_SLO = Math.max(1, Number(__ENV.K6_BREAKPOINT_P95_MS || '700'));
const P99_SLO = Math.max(P95_SLO, Number(__ENV.K6_BREAKPOINT_P99_MS || '1500'));
const MAX_ERROR_RATE = Number(__ENV.K6_BREAKPOINT_MAX_ERROR_RATE || '0.01');
const OPTIMAL_ERROR_RATE = Number(__ENV.K6_BREAKPOINT_OPTIMAL_ERROR_RATE || '0.001');

const targetLatency = new Trend('mreader_target_latency', true);
const targetFailures = new Rate('mreader_target_failures');
const targetRequests = new Counter('mreader_target_requests');
const targetStatus429 = new Counter('mreader_target_status_429');
const isConnections = isConnectionWorkload(WORKLOAD);

export const options = isConnections ? {
  scenarios: { breakpoint: { executor: 'per-vu-iterations', vus: LEVEL, iterations: 1, maxDuration: `${DURATION_SECONDS + 30}s`, exec: 'run' } }, thresholds: {},
} : {
  scenarios: { breakpoint: { executor: 'constant-arrival-rate', rate: LEVEL, timeUnit: '1s', duration: `${DURATION_SECONDS}s`, preAllocatedVUs: Math.min(MAX_VUS, Math.max(10, LEVEL * 2)), maxVUs: MAX_VUS, exec: 'run' } }, thresholds: {},
};

export function setup() { return setupWorkload(WORKLOAD); }
function observe(event) {
  targetRequests.add(1);
  targetFailures.add(!event.ok);
  if (event.status === 429) targetStatus429.add(1);
  targetLatency.add(event.type === 'ws' ? event.duration : event.res.timings.duration);
}
export function run(data) { runWorkload(WORKLOAD, data, observe, 'breakpoint', DURATION_SECONDS - 2); }
function values(data, name) { return (data.metrics[name] && data.metrics[name].values) || {}; }
function num(v, fallback = 0) { return Number.isFinite(Number(v)) ? Number(v) : fallback; }
export function handleSummary(data) {
  const lat=values(data,'mreader_target_latency'), fail=values(data,'mreader_target_failures'), req=values(data,'mreader_target_requests'), dropped=values(data,'dropped_iterations'), status429=values(data,'mreader_target_status_429'), iterations=values(data,'iterations');
  const p50=num(lat['p(50)']), p95=num(lat['p(95)']), p99=num(lat['p(99)']), failureRate=num(fail.rate), targetCount=num(req.count), targetRate=num(req.rate), droppedCount=num(dropped.count), iterationCount=num(iterations.count), droppedRate=(droppedCount+iterationCount)>0?droppedCount/(droppedCount+iterationCount):0, status429Count=num(status429.count);
  const hardPass=failureRate<MAX_ERROR_RATE && p95<=P95_SLO && p99<=P99_SLO && droppedRate<0.005 && targetCount>0;
  const optimalPass=hardPass && failureRate<=OPTIMAL_ERROR_RATE && p95<=P95_SLO*0.70 && p99<=P99_SLO*0.75 && droppedCount===0;
  const state=hardPass?(optimalPass?'OPTIMAL':'PASS'):'FAIL';
  const fields=[WORKLOAD,LEVEL,isConnections?'connections':'rps',targetCount.toFixed(0),targetRate.toFixed(3),p50.toFixed(2),p95.toFixed(2),p99.toFixed(2),failureRate.toFixed(6),droppedCount.toFixed(0),droppedRate.toFixed(6),status429Count.toFixed(0),state];
  return { stdout:`\nMREADER_BREAKPOINT_RESULT=${fields.join('|')}\n` };
}
