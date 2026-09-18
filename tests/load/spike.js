import { Counter, Rate, Trend } from 'k6/metrics';
import { setupWorkload, runWorkload, isConnectionWorkload } from './workload-common.js';

const WORKLOAD = __ENV.K6_BREAKPOINT_WORKLOAD || 'catalog_detail';
const BASE = Math.max(1, Number(__ENV.K6_SPIKE_BASELINE_LEVEL || '5'));
const SPIKE = Math.max(BASE, Number(__ENV.K6_SPIKE_LEVEL || '100'));
const BASE_SECONDS = Math.max(5, Number(__ENV.K6_SPIKE_BASELINE_SECONDS || '20'));
const SPIKE_SECONDS = Math.max(5, Number(__ENV.K6_SPIKE_SECONDS || '15'));
const RECOVERY_SECONDS = Math.max(10, Number(__ENV.K6_SPIKE_RECOVERY_SECONDS || '30'));
const P95_SLO = Math.max(1, Number(__ENV.K6_BREAKPOINT_P95_MS || '700'));
const P99_SLO = Math.max(P95_SLO, Number(__ENV.K6_BREAKPOINT_P99_MS || '1500'));
const MAX_VUS = Math.max(100, Number(__ENV.K6_SPIKE_MAX_VUS || String(Math.min(2000, Math.max(200, SPIKE * 6)))));
const isConnections = isConnectionWorkload(WORKLOAD);

const baselineLatency = new Trend('mreader_spike_baseline_latency', true);
const spikeLatency = new Trend('mreader_spike_peak_latency', true);
const recoveryLatency = new Trend('mreader_spike_recovery_latency', true);
const baselineFailures = new Rate('mreader_spike_baseline_failures');
const spikeFailures = new Rate('mreader_spike_peak_failures');
const recoveryFailures = new Rate('mreader_spike_recovery_failures');
const baselineRequests = new Counter('mreader_spike_baseline_requests');
const spikeRequests = new Counter('mreader_spike_peak_requests');
const recoveryRequests = new Counter('mreader_spike_recovery_requests');
const baselineServerErrors = new Rate('mreader_spike_baseline_server_errors');
const spikeServerErrors = new Rate('mreader_spike_peak_server_errors');
const recoveryServerErrors = new Rate('mreader_spike_recovery_server_errors');
const spikeStatus429 = new Counter('mreader_spike_peak_status_429');

function arrival(name, rate, duration, startTime, exec) {
  return { executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration: `${duration}s`, startTime: `${startTime}s`, preAllocatedVUs: Math.min(MAX_VUS, Math.max(20, rate * 2)), maxVUs: MAX_VUS, exec };
}
function connections(name, vus, duration, startTime, exec) {
  return { executor: 'per-vu-iterations', vus, iterations: 1, maxDuration: `${duration + 10}s`, startTime: `${startTime}s`, exec };
}

export const options = {
  scenarios: isConnections ? {
    baseline: connections('baseline', BASE, BASE_SECONDS, 0, 'baseline'),
    spike: connections('spike', SPIKE, SPIKE_SECONDS, BASE_SECONDS, 'spike'),
    recovery: connections('recovery', BASE, RECOVERY_SECONDS, BASE_SECONDS + SPIKE_SECONDS, 'recovery'),
  } : {
    baseline: arrival('baseline', BASE, BASE_SECONDS, 0, 'baseline'),
    spike: arrival('spike', SPIKE, SPIKE_SECONDS, BASE_SECONDS, 'spike'),
    recovery: arrival('recovery', BASE, RECOVERY_SECONDS, BASE_SECONDS + SPIKE_SECONDS, 'recovery'),
  },
  thresholds: {},
};

export function setup() { return setupWorkload(WORKLOAD); }
function recorder(phase) {
  return (event) => {
    const latency = event.type === 'ws' ? event.duration : event.res.timings.duration;
    const is5xx = Number(event.status || 0) >= 500;
    if (phase === 'baseline') baselineServerErrors.add(is5xx);
    else if (phase === 'spike') spikeServerErrors.add(is5xx);
    else recoveryServerErrors.add(is5xx);
    if (phase === 'spike' && event.status === 429) spikeStatus429.add(1);
    if (phase === 'baseline') { baselineRequests.add(1); baselineFailures.add(!event.ok); baselineLatency.add(latency); }
    else if (phase === 'spike') { spikeRequests.add(1); spikeFailures.add(!event.ok); spikeLatency.add(latency); }
    else { recoveryRequests.add(1); recoveryFailures.add(!event.ok); recoveryLatency.add(latency); }
  };
}
export function baseline(data) { runWorkload(WORKLOAD, data, recorder('baseline'), 'baseline', Math.max(2, BASE_SECONDS - 1)); }
export function spike(data) { runWorkload(WORKLOAD, data, recorder('spike'), 'spike', Math.max(2, SPIKE_SECONDS - 1)); }
export function recovery(data) { runWorkload(WORKLOAD, data, recorder('recovery'), 'recovery', Math.max(2, RECOVERY_SECONDS - 1)); }
function values(data, name) { return (data.metrics[name] && data.metrics[name].values) || {}; }
function num(v) { return Number.isFinite(Number(v)) ? Number(v) : 0; }
function phase(data, prefix) {
  const lat=values(data, `${prefix}_latency`), fail=values(data, `${prefix}_failures`), req=values(data, `${prefix}_requests`);
  return { count:num(req.count), p95:num(lat['p(95)']), p99:num(lat['p(99)']), fail:num(fail.rate) };
}
export function handleSummary(data) {
  const b=phase(data,'mreader_spike_baseline'), s=phase(data,'mreader_spike_peak'), r=phase(data,'mreader_spike_recovery');
  const peak5xx=num(values(data,'mreader_spike_peak_server_errors').rate), r429=num(values(data,'mreader_spike_peak_status_429').count);
  const dropped=num(values(data,'dropped_iterations').count);
  const expected=isConnections ? (BASE + SPIKE + BASE) : (BASE*BASE_SECONDS + SPIKE*SPIKE_SECONDS + BASE*RECOVERY_SECONDS);
  const droppedRate=expected>0 ? dropped/expected : 0;
  const baselinePass=b.count>0 && b.fail<0.01 && b.p95<=P95_SLO && b.p99<=P99_SLO;
  const recoveryPass=r.count>0 && r.fail<0.01 && r.p95<=P95_SLO && r.p99<=P99_SLO;
  // Overload shedding during the peak may include 429s or dropped arrivals. The
  // release invariant is: no sustained server-error storm and full recovery.
  // A spike may shed traffic, but it must still accept a meaningful fraction
  // of delivered requests; 100% 429/failed responses is not 'safe shedding'.
  const peakSafe=s.count>0 && s.fail<0.50 && peak5xx<0.02 && droppedRate<0.25;
  const state=baselinePass && recoveryPass && peakSafe ? 'PASS' : 'FAIL';
  const fields=[WORKLOAD,BASE,SPIKE,isConnections?'connections':'rps',b.count,b.p95.toFixed(2),b.p99.toFixed(2),b.fail.toFixed(6),s.count,s.p95.toFixed(2),s.p99.toFixed(2),s.fail.toFixed(6),r.count,r.p95.toFixed(2),r.p99.toFixed(2),r.fail.toFixed(6),peak5xx.toFixed(6),r429.toFixed(0),dropped.toFixed(0),droppedRate.toFixed(6),state];
  return { stdout:`\nMREADER_SPIKE_RESULT=${fields.join('|')}\n` };
}
