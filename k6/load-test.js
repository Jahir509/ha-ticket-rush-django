import http from 'k6/http';
import {
  API,
  DURATION,
  MODE,
  NODE_ID,
  SUMMARY_FILE,
  TOTAL_RATE,
  VUS,
  WARMUP,
  WARMUP_ENABLED,
  WARMUP_RATE,
  vusFor,
} from './lib/config.js';
import { hit } from './lib/api.js';
import { describeRoutes, pickRoute } from './lib/routes.js';
import { probeHitRate } from './lib/probe.js';
import { SUMMARY_TREND_STATS, makeSummary } from './lib/summary.js';

if (MODE !== 'rate' && MODE !== 'max') {
  throw new Error(`MODE must be "rate" or "max", got "${MODE}".`);
}

const measuredStart = WARMUP_ENABLED ? WARMUP : '0s';

// One scenario for all traffic: each iteration picks a random route from
// routes.js, so reads and writes arrive interleaved in the configured split.
const trafficScenario =
  MODE === 'max'
    ? {
        executor: 'constant-vus',
        exec: 'traffic',
        vus: VUS,
        duration: DURATION,
        startTime: measuredStart,
        gracefulStop: '5s',
      }
    : {
        executor: 'constant-arrival-rate',
        exec: 'traffic',
        rate: TOTAL_RATE,
        timeUnit: '1s',
        duration: DURATION,
        ...vusFor(TOTAL_RATE),
        startTime: measuredStart,
        gracefulStop: '5s',
      };

const scenarios = { traffic: trafficScenario };
if (WARMUP_ENABLED) {
  scenarios.warmup = {
    executor: 'constant-arrival-rate',
    exec: 'warmup',
    rate: WARMUP_RATE,
    timeUnit: '1s',
    duration: WARMUP,
    preAllocatedVUs: 50,
    maxVUs: 200,
    startTime: '0s',
  };
}

export const options = {
  scenarios,
  discardResponseBodies: true,
  setupTimeout: '120s',
  summaryTrendStats: SUMMARY_TREND_STATS,
  // No pass/fail thresholds: this run only measures response time and req/s.
};

const TARGET = MODE === 'max' ? `${VUS} VUs, no pause` : `${TOTAL_RATE} req/s target`;

export function setup() {
  const ping = http.get(`${API}/users/1`, { responseType: 'none' });
  if (ping.status === 0 || ping.status >= 500) {
    throw new Error(
      `API is not reachable at ${API} (status ${ping.status || ping.error}). Start the backend first.`,
    );
  }

  const nodeId = NODE_ID || `n${Math.random().toString(36).slice(2, 8)}`;
  console.log(`node ${nodeId} | mode ${MODE} | ${TARGET} | ${describeRoutes()}`);
  probeHitRate();

  return { nodeId, runId: `${Date.now()}` };
}

export function traffic(data) {
  hit(pickRoute(), data);
}

// Same random mix, just not recorded (record() skips the warmup scenario).
export function warmup(data) {
  hit(pickRoute(), data);
}

export function handleSummary(data) {
  return makeSummary(data, { mode: MODE, target: TARGET, duration: DURATION }, SUMMARY_FILE);
}
