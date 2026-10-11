import http from 'k6/http';
import { scenario } from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';
import { API, LIST_LIMIT, SLOW_MS, emailForId, randomId, randomPage } from './config.js';
import { ROUTE_BY_KEY, ROUTE_LIST } from './routes.js';

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// A 404 means the random id is not in the database. That is a normal answer
// from the API, not a failure, so k6 must not count it in http_req_failed.
// 204 is what DELETE returns.
const GOOD_STATUSES = [200, 201, 204, 404];
http.setResponseCallback(http.expectedStatuses(...GOOD_STATUSES));

// Route key -> label used in the report and as the request's `name` tag.
export const ENDPOINTS = Object.fromEntries(ROUTE_LIST.map((r) => [r.key, r.label]));

// Everything below is recorded for measured traffic only (warm-up is skipped).
export const apiDuration = new Trend('api_duration', true);
export const apiRequests = new Counter('api_requests');
// Status counters count every response with that status, fast or slow.
export const apiStatus200 = new Counter('api_status_200');
export const apiStatus201 = new Counter('api_status_201');
export const apiStatus204 = new Counter('api_status_204');
export const apiStatus404 = new Counter('api_status_404');
export const apiStatus4xx = new Counter('api_status_4xx');
export const apiStatus5xx = new Counter('api_status_5xx');
// Status 0: timeout, refused, reset -- the API never answered.
export const apiNoResponse = new Counter('api_no_response');
// Anything else (1xx/3xx); not expected from this API.
export const apiStatusOther = new Counter('api_status_other');
export const apiErrors = new Counter('api_errors');
// Good status (200/201/204/404) but slower than SLOW_MS. Still a success, reported
// on its own line so slow-but-answered requests stay visible.
export const apiSlow = new Counter('api_slow');
export const apiSuccess = new Rate('api_success');

const endpointDuration = {};
const endpointRequests = {};
const endpointFailed = {};
const endpointSlow = {};
for (const key of Object.keys(ENDPOINTS)) {
  endpointDuration[key] = new Trend(`api_duration_${key}`, true);
  endpointRequests[key] = new Counter(`api_requests_${key}`);
  endpointFailed[key] = new Counter(`api_errors_${key}`);
  endpointSlow[key] = new Counter(`api_slow_${key}`);
}

// One sample of each kind per VU is enough to see what is going wrong.
const errorLog = { error: 0, slow: 0 };

function record(key, res) {
  if (scenario.name === 'warmup') return res;

  const duration = res.timings.duration;
  const goodStatus = GOOD_STATUSES.includes(res.status);
  const slow = goodStatus && duration > SLOW_MS;

  apiRequests.add(1);
  apiDuration.add(duration);
  endpointDuration[key].add(duration);
  endpointRequests[key].add(1);
  apiSuccess.add(goodStatus);

  if (!goodStatus) {
    apiErrors.add(1);
    endpointFailed[key].add(1);
    if (res.status === 0) apiNoResponse.add(1);
    else if (res.status >= 500) apiStatus5xx.add(1);
    else if (res.status >= 400) apiStatus4xx.add(1);
    else apiStatusOther.add(1);
    if (errorLog.error < 1) {
      errorLog.error += 1;
      console.warn(`${ENDPOINTS[key]} -> ${res.status || res.error} after ${duration.toFixed(0)}ms`);
    }
    return res;
  }

  if (res.status === 200) apiStatus200.add(1);
  else if (res.status === 201) apiStatus201.add(1);
  else if (res.status === 204) apiStatus204.add(1);
  else apiStatus404.add(1);

  if (slow) {
    apiSlow.add(1);
    endpointSlow[key].add(1);
    if (errorLog.slow < 1) {
      errorLog.slow += 1;
      console.warn(`${ENDPOINTS[key]} -> ${res.status} but took ${duration.toFixed(0)}ms (> ${SLOW_MS}ms)`);
    }
  }
  return res;
}

// Ids this VU created, newest last. DELETE only takes from here so the seeded
// rows are never removed. Capped so a long run does not grow it forever.
const createdIds = [];
const MAX_CREATED_IDS = 1000;

const uniqueEmail = (data) =>
  `${scenario.name}-${data.nodeId}-${data.runId}-${scenario.iterationInTest}@loadtest.local`;

const json = (body) => JSON.stringify(body);

// One function per route key in routes.js. Each returns the k6 response.
const REQUESTS = {
  by_id: (params) => http.get(`${API}/users/${randomId()}`, params),

  list: (params) => http.get(`${API}/users?page=${randomPage()}&page_size=${LIST_LIMIT}`, params),

  create: (params, data) => {
    const body = json({
      email: uniqueEmail(data),
      first_name: 'Load',
      last_name: `User${scenario.iterationInTest}`,
    });
    // The body is needed for the new id; everything else discards bodies.
    const res = http.post(`${API}/users`, body, { ...params, headers: JSON_HEADERS, responseType: 'text' });
    if (res.status === 201) {
      try {
        createdIds.push(res.json('id'));
        if (createdIds.length > MAX_CREATED_IDS) createdIds.shift();
      } catch (_) {
        // A 201 without a readable id just means nothing to delete later.
      }
    }
    return res;
  },

  // Seeded rows: email stays what the seed gave it, only the names change.
  update: (params) => {
    const id = randomId();
    const body = json({ email: emailForId(id), first_name: 'Load', last_name: `Put${scenario.iterationInTest}` });
    return http.put(`${API}/users/${id}`, body, { ...params, headers: JSON_HEADERS });
  },

  patch: (params) => {
    const body = json({ last_name: `Patch${scenario.iterationInTest}` });
    return http.patch(`${API}/users/${randomId()}`, body, { ...params, headers: JSON_HEADERS });
  },

  delete: (params) => http.del(`${API}/users/${createdIds.pop()}`, null, params),
};

for (const route of ROUTE_LIST) {
  if (!REQUESTS[route.key]) {
    throw new Error(`routes.js has route "${route.key}" but api.js has no request for it.`);
  }
}

export function hit(route, data) {
  // Nothing of our own to delete yet: create one instead of touching seeded rows.
  if (route.key === 'delete' && createdIds.length === 0) route = ROUTE_BY_KEY.create;
  const params = { tags: { name: route.label, kind: route.kind } };
  return record(route.key, REQUESTS[route.key](params, data));
}
