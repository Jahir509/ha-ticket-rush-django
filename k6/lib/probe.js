import http from 'k6/http';
import { API, MAX_ID, MIN_ID, randomId } from './config.js';

// Informational only: shows roughly how many id reads will find a row. A low
// hit rate is fine (404s are measured like any other response), it just means
// most reads are index misses rather than full row fetches.
export function probeHitRate(samples = 20) {
  const requests = [];
  for (let i = 0; i < samples; i += 1) {
    requests.push({ method: 'GET', url: `${API}/users/${randomId()}`, params: { responseType: 'none' } });
  }

  const hits = http.batch(requests).filter((res) => res.status === 200).length;

  console.log(
    `id range ${MIN_ID}..${MAX_ID} | sampled ${samples}: ` +
      `found ${Math.round((hits / samples) * 100)}% (the rest return 404)`,
  );
}
