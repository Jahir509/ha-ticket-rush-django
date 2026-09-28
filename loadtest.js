import http from 'k6/http';
import { Counter } from 'k6/metrics';

const HOST  = __ENV.HOST     || 'http://10.2.116.112:8001';
const EVENT = __ENV.EVENT_ID || '5bc1c8f3';
const RATE  = Number(__ENV.RATE || 4000);

const errors = new Counter('errors_by_code');

export const options = {
  discardResponseBodies: true,
  scenarios: {
    flash: {
      executor: 'constant-arrival-rate',
      rate: RATE, timeUnit: '1s', duration: __ENV.DURATION || '3m',
      preAllocatedVUs: Math.ceil(RATE * 0.4),
      maxVUs: Math.ceil(RATE * 2.5),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    http_req_duration: ['p(99)<500'],
    dropped_iterations: ['count<100'],
  },
};

export default function () {
  const res = http.post(`${HOST}/events/${EVENT}/purchase?user_id=k6`, null, {
    timeout: '10s',
  });

  if (res.status !== 200) {
    console.log(`code=${res.error_code} status=${res.status}`);
  }
}
// k6 run -e RATE=4000 loadtest.js 2>&1 | grep '^INFO.*code='  | sed 's/.*code=/code=/' | sort | uniq -c | sort -rn | head
// k6 run -e EVENT_ID=5bc1c8f3 -e RATE=1000 -e DURATION=1m loadtest.js 2>&1 | tee run1k.log