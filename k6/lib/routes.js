// What the load test hits and how often, taken from users/urls.py:
//
//   users              GET (list), POST (create)
//   users/<int:id>     GET, PUT, PATCH, DELETE
//
// Every iteration first picks read or write by `percent`, then one route in
// that group by `weight`. Weights are relative inside their group, so they do
// not have to add up to 100. A weight of 0 turns the route off.
//
// Override from the command line without editing this file:
//   -e READ_PERCENT=80        write gets the rest (20)
//   -e WEIGHT_DELETE=0        WEIGHT_<KEY in upper case> for any route below
const envNumber = (name, fallback) =>
  __ENV[name] !== undefined && __ENV[name] !== '' ? Number(__ENV[name]) : fallback;

const READ_PERCENT = envNumber('READ_PERCENT', 70);

export const ROUTES = {
  read: {
    percent: READ_PERCENT,
    routes: [
      { key: 'by_id', method: 'GET', path: '/users/:id', weight: 70 },
      { key: 'list', method: 'GET', path: '/users', weight: 30 },
    ],
  },
  write: {
    percent: 100 - READ_PERCENT,
    routes: [
      { key: 'create', method: 'POST', path: '/users', weight: 50 },
      { key: 'update', method: 'PUT', path: '/users/:id', weight: 20 },
      { key: 'patch', method: 'PATCH', path: '/users/:id', weight: 20 },
      // Only deletes rows this VU created itself, never seeded ones.
      { key: 'delete', method: 'DELETE', path: '/users/:id', weight: 10 },
    ],
  },
};

// Flat list with the group name (`kind`) and the env weight override applied.
export const ROUTE_LIST = [];
for (const [kind, group] of Object.entries(ROUTES)) {
  for (const route of group.routes) {
    ROUTE_LIST.push({
      ...route,
      kind,
      weight: envNumber(`WEIGHT_${route.key.toUpperCase()}`, route.weight),
      label: `${route.method} ${route.path}`,
    });
  }
}

export const ROUTE_BY_KEY = Object.fromEntries(ROUTE_LIST.map((r) => [r.key, r]));

const sum = (items, field) => items.reduce((total, item) => total + item[field], 0);

const GROUPS = Object.entries(ROUTES)
  .map(([kind, group]) => {
    const routes = ROUTE_LIST.filter((r) => r.kind === kind && r.weight > 0);
    return { kind, percent: group.percent, routes, total: sum(routes, 'weight') };
  })
  .filter((g) => g.percent > 0);

for (const g of GROUPS) {
  if (g.total <= 0) {
    throw new Error(`"${g.kind}" is ${g.percent}% of traffic but all of its route weights are 0.`);
  }
}
if (GROUPS.length === 0) {
  throw new Error('read and write percent are both 0; nothing to hit.');
}

const GROUP_TOTAL = sum(GROUPS, 'percent');

function pickWeighted(items, field, total) {
  let roll = Math.random() * total;
  for (const item of items) {
    if (roll < item[field]) return item;
    roll -= item[field];
  }
  return items[items.length - 1];
}

export function pickRoute() {
  const group = pickWeighted(GROUPS, 'percent', GROUP_TOTAL);
  return pickWeighted(group.routes, 'weight', group.total);
}

// e.g. "read 70% [GET /users/:id 70, GET /users 30] | write 30% [...]"
export function describeRoutes() {
  return GROUPS.map(
    (g) => `${g.kind} ${g.percent}% [${g.routes.map((r) => `${r.label} ${r.weight}`).join(', ')}]`,
  ).join(' | ');
}
