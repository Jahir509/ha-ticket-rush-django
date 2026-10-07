cat > loadtest_get.js <<'EOF'
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

// GET /users?page=<random> at a constant RATE per second.
//
// Through the domain (Cloudflare tunnel):
//   k6 run -e RATE=1000 loadtest_get.js
// Straight to the VM on the LAN (no Cloudflare). nginx picks the app by
// domain name, so the name goes in the Host header:
//   k6 run -e HOST=http://10.2.116.112 -e VHOST=ticketrush-dj.jahirahmed.com -e RATE=1000 loadtest_get.js
//
// Prints one RESULT line at the end; the full summary goes to summary-<RATE>.json.
// LOG_ERRORS=1 prints every failed request.

const HOST       = __ENV.HOST || 'https://ticketrush-dj.jahirahmed.com';
const VHOST      = __ENV.VHOST || '';
const RATE       = Number(__ENV.RATE || 1000);
const DURATION   = __ENV.DURATION || '1m';
const PAGE_MIN   = Number(__ENV.PAGE_MIN || 1);
const PAGE_MAX   = Number(__ENV.PAGE_MAX || 2500000);
const PAGE_SIZE  = Number(__ENV.PAGE_SIZE || 20);
const LOG_ERRORS = __ENV.LOG_ERRORS === '1';

const PARAMS = {
  timeout: '10s',
  tags: { name: 'GET /users' },
  headers: VHOST ? { Host: VHOST } : {},
};

const timeouts   = new Counter('users_timeouts');     // no answer at all (status 0)
const httpErrors = new Counter('users_http_errors');  // the app answered, but not 200

export const options = {
  discardResponseBodies: true,
  scenarios: {
    users_get: {
      executor: 'constant-arrival-rate',
      rate: RATE, timeUnit: '1s', duration: DURATION,
      preAllocatedVUs: Math.max(10, Math.ceil(RATE * 0.2)),
      maxVUs: Math.max(50, RATE * 2),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

export default function () {
  const page = PAGE_MIN + Math.floor(Math.random() * (PAGE_MAX - PAGE_MIN + 1));
  const res = http.get(`${HOST}/users?page=${page}&page_size=${PAGE_SIZE}`, PARAMS);

  if (check(res, { 'status 200': (r) => r.status === 200 })) return;

  if (res.status === 0) timeouts.add(1);
  else httpErrors.add(1, { status: String(res.status) });

  if (LOG_ERRORS) {
    console.error(`ERROR page=${page} status=${res.status} code=${res.error_code} ms=${res.timings.duration.toFixed(1)}`);
  }
}

export function handleSummary(data) {
  const m = data.metrics;
  const val = (name, key) => (m[name] ? m[name].values[key] : 0);

  const line =
    `RESULT target=${VHOST ? 'LAN' : 'domain'} rate=${RATE}/s` +
    ` sent=${val('http_reqs', 'rate').toFixed(0)}/s` +
    ` failed=${(val('http_req_failed', 'rate') * 100).toFixed(2)}%` +
    ` timeouts=${val('users_timeouts', 'count')}` +
    ` http_errors=${val('users_http_errors', 'count')}` +
    ` p50=${val('http_req_duration', 'med').toFixed(0)}ms` +
    ` p95=${val('http_req_duration', 'p(95)').toFixed(0)}ms` +
    ` dropped=${val('dropped_iterations', 'count')}\n`;

  return {
    stdout: line,
    [`summary-${RATE}.json`]: JSON.stringify(data, null, 2),
  };
}
EOF