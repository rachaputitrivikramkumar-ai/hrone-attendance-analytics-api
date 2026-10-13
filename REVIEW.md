# REVIEW.md

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes()` | The helper does not convert UTC timestamps to IST before calculating lateness. | A UTC-stored timestamp can produce an incorrect late-minute value when passed directly to the helper. | Convert the timestamp to IST before comparing it with the shift start, and apply the 10-minute grace rule. |
| 2 | `compute_work_hours()` | Python's built-in `round()` does not guarantee the required half-up rounding. | A duration near a half-centesimal rounding boundary can produce a different result from the specified rule. | Use `Decimal` with `ROUND_HALF_UP` when calculating reported work hours. |
| 3 | `compute_overtime()` | The helper does not handle overnight shifts and does not enforce the 30-minute minimum. | Test a shift ending after midnight or a punch-out less than 30 minutes after shift end. | Calculate the correct shift-end instant, account for overnight shifts, and count overtime only when it reaches 30 minutes. |
| 4 | `punch_in()` | Checking for an existing record before inserting is not safe when requests arrive concurrently. | Send two punch-in requests for the same employee and date at nearly the same time. | Add a unique compound index on `(emp_code, date)` and handle duplicate-key errors as conflicts. |
| 5 | `list_attendance()` | The starter loads all matching documents into Python before sorting and paginating. | Use a large attendance collection and observe that the endpoint reads many unnecessary documents. | Apply filtering, sorting, skipping and limiting in MongoDB, and count the filtered results separately. |
| 6 | `punch_out()` | The starter searches only the current IST date and mishandles a stored naive UTC punch-in when converting it to IST. | Test a punch-out after midnight for an overnight shift, or compare calculated work hours with known timestamps. | Find the correct open attendance record across dates and consistently treat naive MongoDB datetimes as UTC. |
| 7 | `punch_out()` | Checking that a record is still open and updating it are separate operations, so simultaneous requests can both succeed. | Send two punch-out requests concurrently for the same open record. | Use an atomic conditional update so only one request can change a record whose `punch_out` is still null. |

## Items reviewed and not considered defects

- The `FETCH` stage in a MongoDB query plan is normal when MongoDB uses an index to find matching documents and then retrieves the documents.
- A `null` average or attendance rate can be valid when there are no eligible records or the date is not a working day.
- A weekday with no attendance record is different from a record explicitly marked `ABSENT`, so these cases should not automatically be treated as equivalent.