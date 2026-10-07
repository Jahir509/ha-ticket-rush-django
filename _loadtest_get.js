import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';

// GET /users?page=<random PAGE_MIN..PAGE_MAX> at a constant RATE per second.
//
//   k6 run loadtest_get.js
//   k6 run -e RATE=200 -e DURATION=5m -e PAGE_MAX=5000 loadtest_get.js
//   k6 run -e LOG_ALL=1 loadtest_get.js 2>&1 | tee get.log     # log every request
//
// Pages start at 1; page=0 returns 400. Every page is an id seek, so deep
// pages cost the same as page 1; pages past the last row return [].

const HOST      = __ENV.HOST || 'https://ticketrush-dj.jahirahmed.com';
const RATE      = Number(__ENV.RATE || 2000);
const DURATION  = __ENV.DURATION || '1m';
const PAGE_MIN  = Number(__ENV.PAGE_MIN || 1);
const PAGE_MAX  = Number(__ENV.PAGE_MAX || 2500000);
const PAGE_SIZE = Number(__ENV.PAGE_SIZE || 20);
const SLOW_MS   = Number(__ENV.SLOW_MS || 500);   // log requests slower than this
const LOG_ALL   = __ENV.LOG_ALL === '1';

const errorsByStatus = new Counter('users_errors');
const slowRequests   = new Counter('users_slow');
const resultRows     = new Trend('users_rows_returned');

export const options = {
  scenarios: {
    users_get: {
      executor: 'constant-arrival-rate',
      rate: RATE, timeUnit: '1s', duration: DURATION,
      preAllocatedVUs: Math.max(10, Math.ceil(RATE * 0.5)),
      maxVUs: Math.max(50, RATE * 5),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    dropped_iterations: ['count<10'],
  },
};

export function setup() {
  console.log(`target=${HOST}/users rate=${RATE}/s duration=${DURATION} pages=${PAGE_MIN}-${PAGE_MAX} page_size=${PAGE_SIZE}`);
}

export default function () {
  const page = PAGE_MIN + Math.floor(Math.random() * (PAGE_MAX - PAGE_MIN + 1));
  const url = `${HOST}/users?page=${page}&page_size=${PAGE_SIZE}`;

  // name groups every page under one URL in the k6 summary.
  const res = http.get(url, { timeout: '10s', tags: { name: 'GET /users' } });
  const ms = res.timings.duration.toFixed(1);

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'has results': (r) => r.status === 200 && Array.isArray(r.json('results')),
  });

  if (res.status === 200) {
    resultRows.add(res.json('results').length);
  }

  if (!ok) {
    errorsByStatus.add(1, { status: String(res.status) });
    const body = (res.body || '').toString().slice(0, 200).replace(/\s+/g, ' ');
    console.error(`ERROR page=${page} status=${res.status} code=${res.error_code} ms=${ms} body=${body}`);
  } else if (res.timings.duration > SLOW_MS) {
    slowRequests.add(1);
    console.warn(`SLOW page=${page} status=${res.status} ms=${ms}`);
  } else if (LOG_ALL) {
    console.log(`OK page=${page} status=${res.status} ms=${ms}`);
  }
}

// Summary:
//   k6 run loadtest_get.js 2>&1 | tee get.log
//   grep -oE '(ERROR|SLOW) .*status=[0-9]+' get.log | awk '{print $1, $3}' | sort | uniq -c | sort -rn




// sudo vi loadtest_get.js
// k6 -e RATE=2000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get2k.log
// k6 -e RATE=3000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get3k.log
// k6 -e RATE=4000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get4k.log
// k6 -e RATE=5000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get5k.log
// k6 -e RATE=7000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get7k.log
// k6 -e RATE=10000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get10k.log
// k6 -e RATE=12000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get12k.log
// k6 -e RATE=15000 -e DURATION=3m run loadtest_get.js 2>&1 | tee get15k.log

