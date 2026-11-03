

from math import ceil


def paginate(items, page: int = 1, per_page: int = 10):
    """Generic pagination helper."""
    total = len(items)
    if total == 0:
        return [], 1, 1

    total_pages = ceil(total / per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page

    return items[start:end], page, total_pages