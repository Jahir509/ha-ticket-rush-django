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

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import User

# id and created_at are set by the server, never by the client.
WRITABLE_FIELDS = ("email", "first_name", "last_name")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


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
    No COUNT(*): on a 50M-row table it is a full scan that outlives the
    gunicorn worker timeout. Fetch one row past the page instead to know
    whether a next page exists.

    No OFFSET either: it walks every skipped index entry, so deep pages time
    out. ?page=N is turned into an id cursor instead. ids are dense (bulk
    COPY, consecutive ranges), so page N starts at first_id + (N - 1) *
    page_size and is fetched with an index seek, the same cost at any depth.

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

    qs = User.objects.order_by("id")
    first_id = qs.values_list("id", flat=True).first()
    rows, has_next = [], False
    if first_id is not None:
        start = first_id + (page_number - 1) * page_size
        end = start + page_size
        # [start, end) holds at most page_size ids, so row page_size + 1, if
        # any, is past it and proves a next page exists.
        fetched = list(qs.filter(id__gte=start)[: page_size + 1])
        rows = [user for user in fetched if user.id < end]
        has_next = len(fetched) > len(rows)

    return JsonResponse({
        "page": page_number,
        "page_size": page_size,
        "next": page_number + 1 if has_next else None,
        "previous": page_number - 1 if page_number > 1 else None,
        "results": [user.to_dict() for user in rows],
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
