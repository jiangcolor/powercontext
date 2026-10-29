"""Small ticket-listing service; the status parameter is not implemented yet."""


def list_tickets(records, *, status=None, limit=10):
    """Return newest tickets without changing the caller's data."""
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    return sorted(records, key=lambda row: (row["created_at"], row["id"]), reverse=True)[:limit]
