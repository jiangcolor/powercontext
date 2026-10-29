# Ticket listing specification — version 1

SPEC-STATUS: Add an exact status filter to list_tickets. Accepted values are
open, in_progress, closed. status=None returns all statuses. An unsupported
status must raise ValueError, including on an empty collection. An accepted
status with no matches returns an empty list. Filtering happens before limit.

SPEC-COMPAT: Preserve the existing newest-created-first order, breaking a tie
by descending id. Keep the default limit of 10 and limit=0 returning an empty
list. Invalid limits still raise ValueError. Do not mutate input records.

Sources: code demo/before/tickets.py, function list_tickets;
verification demo/tests/test_tickets.py, TargetStatusTests and RegressionTests.
