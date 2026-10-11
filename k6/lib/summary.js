import { ENDPOINTS } from './api.js';
import { NATIVE_SUMMARY, SLOW_MS, durationSeconds } from './config.js';

const TREND_STATS = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'];
export const SUMMARY_TREND_STATS = TREND_STATS;

const metric = (data, name) => (data.metrics[name] ? data.metrics[name].values : null);
const count = (data, name) => (metric(data, name) ? metric(data, name).count : 0);

const ms = (v) => (v === undefined || v === null ? '-' : `${v.toFixed(2)}ms`);
const num = (v, digits = 0) => Number(v).toFixed(digits);
const pct = (part, whole) => (whole > 0 ? `${((part / whole) * 100).toFixed(2)}%` : '-');
const pad = (s, n) => String(s).padEnd(n);
const lpad = (s, n) => String(s).padStart(n);

function latency(values) {
  const out = {};
  for (const stat of TREND_STATS) out[stat] = values ? values[stat] : null;
  return out;
}

// Builds the numbers once so the console report and the JSON file agree.
function buildReport(data, meta) {
  const seconds = durationSeconds(meta.duration);
  const total = count(data, 'api_requests');
  const ok200 = count(data, 'api_status_200');
  const created201 = count(data, 'api_status_201');
  const noContent204 = count(data, 'api_status_204');
  const notFound404 = count(data, 'api_status_404');
  const slow = count(data, 'api_slow');
  const success = ok200 + created201 + noContent204 + notFound404;
  const client4xx = count(data, 'api_status_4xx');
  const server5xx = count(data, 'api_status_5xx');
  const noResponse = count(data, 'api_no_response');
  const other = count(data, 'api_status_other');
  const failed = client4xx + server5xx + noResponse + other;

  const endpoints = {};
  for (const [key, label] of Object.entries(ENDPOINTS)) {
    const values = metric(data, `api_duration_${key}`);
    const n = count(data, `api_requests_${key}`);
    if (n === 0) continue;
    endpoints[label] = {
      requests: n,
      req_per_sec: seconds > 0 ? n / seconds : 0,
      failed: count(data, `api_errors_${key}`),
      slow: count(data, `api_slow_${key}`),
      latency_ms: latency(values),
    };
  }

  return {
    mode: meta.mode,
    target: meta.target,
    measured_seconds: seconds,
    slow_ms: SLOW_MS,
    requests: {
      total,
      success,
      status_200: ok200,
      status_201: created201,
      status_204: noContent204,
      status_404: notFound404,
      slow,
      failed,
      status_4xx: client4xx,
      status_5xx: server5xx,
      no_response: noResponse,
      status_other: other,
      success_rate: total > 0 ? success / total : 0,
    },
    throughput: {
      req_per_sec: seconds > 0 ? total / seconds : 0,
      successful_req_per_sec: seconds > 0 ? success / seconds : 0,
      fast_req_per_sec: seconds > 0 ? (success - slow) / seconds : 0,
    },
    latency_ms: latency(metric(data, 'api_duration')),
    endpoints,
    dropped_iterations: count(data, 'dropped_iterations'),
  };
}

// k6's own counters. These cover EVERY request k6 made -- warm-up and the
// setup() probe included -- whereas the api_* counters above are the measured
// window only, so the two totals are expected to differ.
function buildNative(data) {
  const reqs = metric(data, 'http_reqs');
  const failed = metric(data, 'http_req_failed');
  const checks = metric(data, 'checks');
  const iterations = metric(data, 'iterations');
  const vus = metric(data, 'vus_max');
  const received = metric(data, 'data_received');
  const sent = metric(data, 'data_sent');

  // http_req_failed is a Rate: `passes` counts the requests that WERE
  // failures, `fails` the ones that were fine. Verified, not assumed.
  const bad = failed ? failed.passes : 0;
  const good = failed ? failed.fails : 0;

  return {
    http_reqs: reqs ? reqs.count : 0,
    http_reqs_per_sec: reqs ? reqs.rate : 0,
    http_req_failed: bad,
    http_req_ok: good,
    http_req_failed_rate: failed ? failed.rate : 0,
    checks_passed: checks ? checks.passes : null,
    checks_failed: checks ? checks.fails : null,
    iterations: iterations ? iterations.count : 0,
    dropped_iterations: count(data, 'dropped_iterations'),
    vus_max: vus ? vus.max : 0,
    data_received_mb: received ? received.count / 1e6 : 0,
    data_sent_mb: sent ? sent.count / 1e6 : 0,
  };
}

function nativeText(n) {
  const lines = [];
  const line = (s = '') => lines.push(s);
  const row = (label, value) => line(`  ${pad(label, 22)}${value}`);
  const total = n.http_req_failed + n.http_req_ok;

  line();
  line('K6 NATIVE COUNTERS (includes warm-up and the setup probe)');
  row('http_reqs', `${n.http_reqs}  (${num(n.http_reqs_per_sec, 1)}/s)`);
  row('ok', `${n.http_req_ok}  ${pct(n.http_req_ok, total)}   (200/201/204/404, any speed)`);
  row('failed', `${n.http_req_failed}  ${pct(n.http_req_failed, total)}   (any other status, or no response)`);
  if (n.checks_passed !== null) {
    row('checks', `${n.checks_passed} passed / ${n.checks_failed} failed`);
  } else {
    row('checks', 'none defined -- this suite asserts via api_errors instead');
  }
  row('iterations', n.iterations);
  row('dropped_iterations', n.dropped_iterations);
  row('vus_max', n.vus_max);
  row('data received / sent', `${num(n.data_received_mb, 1)} MB / ${num(n.data_sent_mb, 1)} MB`);
  return lines.join('\n');
}

function toText(r) {
  const lines = [];
  const line = (s = '') => lines.push(s);

  line();
  line('================ API LOAD TEST RESULT ================');
  line(`mode              ${r.mode}  (${r.target})`);
  line(`measured window   ${r.measured_seconds}s`);
  line();
  line('THROUGHPUT');
  line(`  requests/sec          ${num(r.throughput.req_per_sec, 1)}`);
  line(`  successful req/sec    ${num(r.throughput.successful_req_per_sec, 1)}   (200/201/204/404, any speed)`);
  line(`    within ${pad(`${r.slow_ms}ms`, 13)}${num(r.throughput.fast_req_per_sec, 1)}`);
  line();
  const q = r.requests;
  const row = (label, value, note = '') =>
    line(`${pad(label, 24)}${lpad(value, 8)}  ${lpad(pct(value, q.total), 7)}${note ? `   ${note}` : ''}`);
  line('REQUESTS');
  line(`${pad('  total', 24)}${lpad(q.total, 8)}`);
  line();
  row('  SUCCESS', q.success, '(200/201/204/404)');
  row('    200 OK', q.status_200);
  row('    201 Created', q.status_201);
  row('    204 No Content', q.status_204);
  row('    404 Not Found', q.status_404, '<- no row in DB, not an error');
  row(`    slow (>${r.slow_ms}ms)`, q.slow, '<- counted above, but answered too late');
  line();
  row('  FAILED', q.failed);
  row('    4xx', q.status_4xx, '<- client error (bad request, validation, conflict)');
  row('    5xx', q.status_5xx, '<- server error (incl. DB timeout)');
  row('    no response', q.no_response, '<- timeout, refused, connection reset');
  if (q.status_other > 0) row('    other', q.status_other, '<- unexpected 1xx/3xx');
  line();
  line('RESPONSE TIME (all endpoints)');
  for (const stat of TREND_STATS) line(`  ${pad(stat, 8)}${lpad(ms(r.latency_ms[stat]), 14)}`);
  line();
  line('PER ENDPOINT');
  line(
    `  ${pad('endpoint', 26)}${lpad('reqs', 9)}${lpad('req/s', 10)}${lpad('avg', 11)}` +
      `${lpad('p95', 11)}${lpad('p99', 11)}${lpad('slow', 8)}${lpad('failed', 8)}`,
  );
  for (const [label, e] of Object.entries(r.endpoints)) {
    line(
      `  ${pad(label, 26)}${lpad(e.requests, 9)}${lpad(num(e.req_per_sec, 1), 10)}` +
        `${lpad(ms(e.latency_ms.avg), 11)}${lpad(ms(e.latency_ms['p(95)']), 11)}` +
        `${lpad(ms(e.latency_ms['p(99)']), 11)}${lpad(e.slow, 8)}${lpad(e.failed, 8)}`,
    );
  }

  // In max mode only the warm-up uses an arrival rate, so any drops happened
  // there and say nothing about the measured window.
  if (r.dropped_iterations > 0 && r.mode === 'max') {
    line();
    line(`NOTE: ${r.dropped_iterations} warm-up requests were dropped; the measured window is unaffected.`);
  } else if (r.dropped_iterations > 0) {
    line();
    line(
      `NOTE: ${r.dropped_iterations} requests could not be started on time (dropped_iterations).`,
    );
    line('      The API could not keep up with the target rate, or k6 ran out of VUs;');
    line('      "requests/sec" above is what was actually achieved.');
  }
  line('======================================================');
  line();
  return lines.join('\n');
}

export function makeSummary(data, meta, file) {
  const report = buildReport(data, meta);
  report.k6_native = buildNative(data);

  let stdout = toText(report);
  if (NATIVE_SUMMARY) stdout += nativeText(report.k6_native) + '\n';

  const out = { stdout };
  if (file) out[file] = JSON.stringify(report, null, 2);
  return out;
}
