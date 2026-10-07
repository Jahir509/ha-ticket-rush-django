"""
Plain function views for users CRUD, same style as tickets.views: no DRF,
no class-based or generic views, JSON in and out.

    GET    /users              list, paginated (?page=1&page_size=20)
    POST   /users              create
    GET    /users/<id>         retrieve
    PUT    /users/<id>         full update, every writable field required
    PATCH  /users/<id>         partial update
    DELETE /users/<id>         delete
"""
import json
import time

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import User

# id and created_at are set by the server, never by the client.
WRITABLE_FIELDS = ("email", "first_name", "last_name")

# Columns the list returns. .values() hands back plain dicts straight from
# the cursor, skipping one model object per row.
LIST_FIELDS = ("id", "email", "first_name", "last_name", "created_at")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# The smallest id only changes if the very first user is deleted, so each
# worker asks Postgres at most once a minute instead of on every request.
FIRST_ID_TTL = 60.0
_first_id_cache = {"value": None, "at": 0.0}


# ----------------------------------------------------------------- routes

@csrf_exempt
@require_http_methods(["GET", "POST"])
def users(request):
    if request.method == "GET":
        return list_users(request)
    return create_user(request)


@csrf_exempt
@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
def user_detail(request, user_id):
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return JsonResponse({"detail": "user not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(user.to_dict())
    if request.method == "DELETE":
        user.delete()
        return HttpResponse(status=204)
    return update_user(request, user, partial=request.method == "PATCH")


# ---------------------------------------------------------------- actions

def list_users(request):
    """
    No COUNT(*) and no OFFSET: both walk the table, so deep pages would
    time out. ids are dense (bulk COPY, consecutive ranges), so page N
    starts at first_id + (N - 1) * page_size and is one index seek, the
    same cost at any depth.

    One query per request: first_id is cached per worker, and the page
    fetches one row past its range to learn whether a next page exists.

    Gaps in id (deleted rows) make that page shorter rather than shifting
    rows onto the next page, so no row is skipped or shown twice.
    """
    try:
        page_number = _positive_int(request.GET.get("page"), 1)
        page_size = min(
            _positive_int(request.GET.get("page_size"), DEFAULT_PAGE_SIZE),
            MAX_PAGE_SIZE,
        )
    except ValueError:
        return JsonResponse(
            {"detail": "page and page_size must be positive integers"},
            status=400,
        )

    first_id = _first_user_id()
    rows, has_next = [], False
    if first_id is not None:
        start = first_id + (page_number - 1) * page_size
        end = start + page_size
        # [start, end) holds at most page_size ids, so row page_size + 1, if
        # any, is past it and proves a next page exists.
        fetched = list(
            User.objects.filter(id__gte=start)
            .order_by("id")
            .values(*LIST_FIELDS)[: page_size + 1]
        )
        rows = [row for row in fetched if row["id"] < end]
        has_next = len(fetched) > len(rows)

    return JsonResponse({
        "page": page_number,
        "page_size": page_size,
        "next": page_number + 1 if has_next else None,
        "previous": page_number - 1 if page_number > 1 else None,
        "results": rows,
    })


def create_user(request):
    data, error = _read_body(request, partial=False)
    if error:
        return error

    user = User(**data)
    return _save(user, status=201)


def update_user(request, user, partial):
    data, error = _read_body(request, partial=partial)
    if error:
        return error

    for field, value in data.items():
        setattr(user, field, value)
    return _save(user, status=200)


# ---------------------------------------------------------------- helpers

def _first_user_id():
    now = time.monotonic()
    if (_first_id_cache["value"] is None
            or now - _first_id_cache["at"] > FIRST_ID_TTL):
        _first_id_cache["value"] = (
            User.objects.order_by("id").values_list("id", flat=True).first()
        )
        _first_id_cache["at"] = now
    return _first_id_cache["value"]


def _read_body(request, partial):
    """
    Returns (data, None) on success or (None, JsonResponse) on failure.
    Only WRITABLE_FIELDS are picked up; anything else in the body is ignored.
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None, JsonResponse({"detail": "invalid json"}, status=400)
    if not isinstance(body, dict):
        return None, JsonResponse(
            {"detail": "body must be a json object"}, status=400
        )

    data, errors = {}, {}
    for field in WRITABLE_FIELDS:
        if field not in body:
            if not partial:
                errors[field] = ["This field is required."]
            continue
        value = body[field]
        if not isinstance(value, str):
            errors[field] = ["Must be a string."]
            continue
        data[field] = value.strip()

    if errors:
        return None, JsonResponse(
            {"detail": "validation failed", "errors": errors}, status=400
        )
    return data, None


def _save(user, status):
    try:
        user.full_clean()
    except ValidationError as exc:
        return JsonResponse(
            {"detail": "validation failed", "errors": exc.message_dict},
            status=400,
        )
    user.save()
    return JsonResponse(user.to_dict(), status=status)


def _positive_int(raw, default):
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(raw)
    return value