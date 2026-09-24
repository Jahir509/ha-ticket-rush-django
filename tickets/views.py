"""
Plain Django views, no DRF. DRF's serializers, content negotiation and
exception handling add real per-request cost, and this comparison is more
interesting if Django gets its best shot.
"""
import json
import socket
import uuid
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .redis_client import client, purchase_script

# Resolved once at import. socket.gethostname() in a view would be a
# blocking call on the request path for a value that never changes.
HOSTNAME = socket.gethostname()


# --------------------------------------------------------------- hot path

@csrf_exempt
@require_POST
def purchase(request, event_id):
    """
    The endpoint every load test hits. One Valkey round trip, a few strings,
    no database, no lock, no transaction. That is the whole reason this can
    answer in single-digit milliseconds.
    """
    user_id = request.GET.get("user_id", "anon")
    order_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    left = purchase_script(
        keys=[f"event:{event_id}:remaining", settings.STREAM_KEY],
        args=[order_id, event_id, user_id, ts, settings.STREAM_MAXLEN],
    )

    if left == -2:
        return JsonResponse({"detail": "event not found"}, status=404)
    if left == -1:
        # Correct answer, not a server error. k6 counts 4xx as a pass.
        return JsonResponse({"detail": "sold out"}, status=409)

    return JsonResponse(
        {
            "order_id": order_id,
            "event_id": event_id,
            "status": "confirmed",
            "remaining_tickets": left,
        }
    )


# ----------------------------------------------------------------- events

@csrf_exempt
@require_POST
def create_event(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid json"}, status=400)

    name = body.get("name")
    total = body.get("total_tickets")
    if not name or not isinstance(total, int) or total < 0:
        return JsonResponse(
            {"detail": "name and a non-negative integer total_tickets required"},
            status=400,
        )

    event_id = uuid.uuid4().hex[:8]
    client.hset(
        f"event:{event_id}",
        mapping={
            "name": name,
            "total_tickets": total,
            "price_cents": body.get("price_cents", 0),
        },
    )
    # The counter lives in its own key, not inside the hash, because DECR
    # only works on a standalone key and the Lua script needs DECR.
    client.set(f"event:{event_id}:remaining", total)

    return JsonResponse(
        {"event_id": event_id, "name": name, "total_tickets": total}
    )


@require_GET
def get_event(request, event_id):
    data = client.hgetall(f"event:{event_id}")
    if not data:
        return JsonResponse({"detail": "event not found"}, status=404)
    remaining = client.get(f"event:{event_id}:remaining")
    return JsonResponse({**data, "remaining_tickets": int(remaining or 0)})


@require_GET
def stats(request, event_id):
    data = client.hgetall(f"event:{event_id}")
    if not data:
        return JsonResponse({"detail": "event not found"}, status=404)

    total = int(data.get("total_tickets", 0))
    remaining = int(client.get(f"event:{event_id}:remaining") or 0)

    return JsonResponse(
        {
            "event_id": event_id,
            "name": data.get("name"),
            "total_tickets": total,
            # Derived, not a second counter. A separate counter would drift
            # forever if a process died between DECR and INCR.
            "sold_tickets": total - remaining,
            "remaining_tickets": remaining,
            "oversold": remaining < 0,
            # Total entries ever, not the backlog: MAXLEN keeps history
            # around long after the rows reach Postgres. Use XPENDING to
            # see whether the drain is actually behind.
            "stream_length": client.xlen(settings.STREAM_KEY),
        }
    )


# ----------------------------------------------------------------- probes

@require_GET
def healthz(request):
    """Is the process alive. Checks nothing else on purpose."""
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request):
    """Can it actually serve. socket_timeout keeps this from hanging."""
    try:
        client.ping()
    except Exception:
        return JsonResponse({"detail": "valkey unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


@require_GET
def info(request):
    return JsonResponse(
        {
            "host": HOSTNAME,
            "stack": "django-sync",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
