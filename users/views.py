"""
Plain function views for users CRUD, same style as tickets.views: no DRF,
no class-based or generic views, JSON in and out.

    GET    /users              list, paginated (?page=1&page_size=20)
    POST   /users              create
    GET    /users/<id>         retrieve
    PUT    /users/<id>         full update, every writable field required
    PATCH  /users/<id>         partial update
    DELETE /users/<id>         delete

Every write is exactly one SQL statement:

    POST          INSERT ... RETURNING id
    PUT / PATCH   UPDATE ... WHERE id = %s RETURNING ...
    DELETE        DELETE ... WHERE id = %s   (no BEGIN/COMMIT around it)

No SELECT first to check that the email is free or that the row exists:
Postgres already knows both. A duplicate email comes back as an
IntegrityError (409), a missing row as zero rows (404).
"""
import json
import time

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
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

# Quoted table and column names for the hand-written UPDATE. They come from
# the model, never from the request.
_q = connection.ops.quote_name
_TABLE = _q(User._meta.db_table)
_COLUMN = {f: _q(User._meta.get_field(f).column) for f in LIST_FIELDS}
_RETURNING = ", ".join(_COLUMN[f] for f in LIST_FIELDS)


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
    if request.method == "GET":
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return _not_found()
        return JsonResponse(user.to_dict())
    if request.method == "DELETE":
        return delete_user(user_id)
    return update_user(request, user_id, partial=request.method == "PATCH")


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
    try:
        user = User.objects.create(**data)          # one INSERT ... RETURNING id
    except IntegrityError:
        return _conflict()
    return JsonResponse(user.to_dict(), status=201)


def update_user(request, user_id, partial):
    data, error = _read_body(request, partial=partial)
    if error:
        return error
    if not data:
        # PATCH with nothing to change: answer with the row as it is.
        user = User.objects.filter(pk=user_id).first()
        return JsonResponse(user.to_dict()) if user else _not_found()

    # Only the columns the client sent. Untouched indexed columns (email)
    # stay out of the statement, which lets Postgres do a cheaper in-page
    # (HOT) update when only names change.
    assignments = ", ".join(f"{_COLUMN[f]} = %s" for f in data)
    sql = (f"UPDATE {_TABLE} SET {assignments} "
           f"WHERE {_COLUMN['id']} = %s RETURNING {_RETURNING}")
    try:
        with connection.cursor() as cur:
            cur.execute(sql, [*data.values(), int(user_id)])
            row = cur.fetchone()
    except IntegrityError:
        return _conflict()
    if row is None:
        return _not_found()
    return JsonResponse(_row_to_dict(row))


def delete_user(user_id):
    # Plain DELETE in autocommit: one round trip. Django's QuerySet.delete()
    # would wrap even a single-row delete in BEGIN/COMMIT, three round trips.
    # It also skips pre_delete/post_delete signals; add them back here if a
    # receiver is ever registered for User.
    with connection.cursor() as cur:
        cur.execute(f"DELETE FROM {_TABLE} WHERE {_COLUMN['id']} = %s", [int(user_id)])
        deleted = cur.rowcount
    if not deleted:
        return _not_found()
    return HttpResponse(status=204)


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

    Only WRITABLE_FIELDS are picked up; anything else in the body is
    ignored. Each value is checked by its model field (email format,
    max_length, blank) without touching the database; uniqueness is left
    to the unique index.
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
        try:
            data[field] = User._meta.get_field(field).clean(value.strip(), None)
        except ValidationError as exc:
            errors[field] = exc.messages

    if errors:
        return None, JsonResponse(
            {"detail": "validation failed", "errors": errors}, status=400
        )
    return data, None


def _row_to_dict(row):
    out = {}
    for name, value in zip(LIST_FIELDS, row):
        out[name] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


def _not_found():
    return JsonResponse({"detail": "user not found"}, status=404)


def _conflict():
    return JsonResponse(
        {"detail": "a user with this email already exists"}, status=409
    )


def _positive_int(raw, default):
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(raw)
    return value
