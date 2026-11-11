"""Minimal pagination helper shared by list endpoints.

Keeps one consistent envelope for paginated API responses:
    {"items": [...], "total": int, "page": int, "page_size": int}
"""
from __future__ import annotations

from django.core.paginator import Paginator

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def paginate(queryset, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """Paginate a queryset and return the standard envelope (items as a list)."""
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)
    return {
        "items": list(page_obj.object_list),
        "total": paginator.count,
        "page": page_obj.number,
        "page_size": page_size,
    }
