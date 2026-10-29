"""Small ticket-listing service."""


def list_tickets(records, *, status=None, limit=10):
    """Return newest tickets without changing the caller's data."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    if status is not None and status not in ("open", "in_progress", "closed"):
        raise ValueError("status must be one of: open, in_progress, closed")

    if status is None:
        filtered_records = list(records)
    else:
        filtered_records = [row for row in records if row["status"] == status]

    return sorted(
        filtered_records,
        key=lambda row: (row["created_at"], row["id"]),
        reverse=True,
    )[:limit]
