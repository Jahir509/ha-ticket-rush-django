cd "$(dirname "$0")"

USAGE='usage: ./run-steps.sh <label> [--mode rate|max] [--steps "1000 2000 3000"] [--read-percent 70] [--duration 10m] [--base-url URL] [--cooldown 30] [extra k6 args...]

  --mode rate   each step is a target req/s (default)
  --mode max    each step is a VU count, no pause between requests
  routes and their weights: k6/lib/routes.js'
LABEL="${1:?$USAGE}"
shift

# Defaults; env vars of the same name still work, flags win over both.
BASE_URL="${BASE_URL:-https://ticketrush-dj.jahirahmed.com}"
MODE="${MODE:-rate}"
STEPS="${STEPS:-3000}"
READ_PERCENT="${READ_PERCENT:-70}"
DURATION="${DURATION:-10m}"
COOLDOWN="${COOLDOWN:-30}"

# Flags first; anything after them (or after --) goes to k6 as is.
while [ $# -gt 0 ]; do
  case "$1" in
    --mode)     MODE="${2:?--mode needs a value}"; shift 2 ;;
    --steps)    STEPS="${2:?--steps needs a value}"; shift 2 ;;
    --read-percent) READ_PERCENT="${2:?--read-percent needs a value}"; shift 2 ;;
    --duration) DURATION="${2:?--duration needs a value}"; shift 2 ;;
    --base-url) BASE_URL="${2:?--base-url needs a value}"; shift 2 ;;
    --cooldown) COOLDOWN="${2:?--cooldown needs a value}"; shift 2 ;;
    -h|--help)  echo "$USAGE"; exit 0 ;;
    --)         shift; break ;;
    *)          break ;;
  esac
done

case "$MODE" in
  rate) STEP_VAR=RATE; STEP_NAME=rate; STEP_UNIT='req/s' ;;
  max)  STEP_VAR=VUS;  STEP_NAME=vus;  STEP_UNIT='users' ;;
  *)    echo "--mode must be rate or max, got '$MODE'" >&2; exit 1 ;;
esac

OUT="k6/results/${LABEL}"
mkdir -p "$OUT"

for step in $STEPS; do
  echo
  echo ">>> ${LABEL}: ${MODE} mode, ${step} ${STEP_UNIT}, ${READ_PERCENT}% read, for ${DURATION} against ${BASE_URL}"
  k6 run \
    -e BASE_URL="$BASE_URL" \
    -e MODE="$MODE" \
    -e "${STEP_VAR}=${step}" \
    -e READ_PERCENT="$READ_PERCENT" \
    -e DURATION="$DURATION" \
    -e SUMMARY_FILE="${OUT}/${STEP_NAME}-${step}.json" \
    "$@" \
    k6/load-test.js 2>&1 | tee "${OUT}/${STEP_NAME}-${step}.txt"

  if [ "$step" != "${STEPS##* }" ]; then
    echo ">>> cooling down ${COOLDOWN}s"
    sleep "$COOLDOWN"
  fi
done

{
  echo
  echo "================ ${LABEL}: STEP COMPARISON (${MODE} mode, ${READ_PERCENT}% read) ================"
  printf '%-6s %10s %10s %10s %9s %8s %8s %10s %10s %10s\n' \
    "$STEP_NAME" 'req/s' 'ok req/s' total failed 'fail %' slow p50 p95 p99
  for step in $STEPS; do
    jq -r --arg step "$step" '
      def ms: if . == null then "-" else "\(. * 100 | round / 100)ms" end;
      [ $step,
        (.throughput.req_per_sec | round),
        (.throughput.successful_req_per_sec | round),
        .requests.total,
        .requests.failed,
        (if .requests.total > 0 then (.requests.failed / .requests.total * 10000 | round / 100 | tostring) + "%" else "-" end),
        .requests.slow,
        (.latency_ms.med | ms),
        (.latency_ms["p(95)"] | ms),
        (.latency_ms["p(99)"] | ms)
      ] | @tsv' "${OUT}/${STEP_NAME}-${step}.json" |
      awk -F'\t' '{ printf "%-6s %10s %10s %10s %9s %8s %8s %10s %10s %10s\n", $1,$2,$3,$4,$5,$6,$7,$8,$9,$10 }'
  done
  echo "failed = 4xx (not 404) + 5xx + no response; slow = 200/201/204/404 slower than SLOW_MS (3s), not counted as failed"
  echo "==========================================================="
} | tee "${OUT}/comparison.txt"
