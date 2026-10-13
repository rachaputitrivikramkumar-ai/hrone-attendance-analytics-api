# DECISIONS.md

## 1. Indexes
I created a unique index on `employees.emp_code` to prevent duplicate employee codes. The unique compound index on `attendance_logs(emp_code, date)` prevents duplicate attendance records for the same employee and date. Other indexes support date-based attendance queries, employee attendance history, and date/status filtering. I considered relying only on the unique compound index, but separate indexes support different query patterns.

## 2. Punch-in race
If two identical punch-in requests arrive together, both may check for an existing record. The unique compound index prevents MongoDB from storing duplicate records. One request should succeed, while the other may receive a duplicate-key error. The API should return HTTP 409 for the losing request.

## 3. Ties
The leaderboard uses MongoDB `$rank`. Employees with equal total late minutes receive the same rank. Filtering by `rank <= limit` returns all employees tied at the cutoff rank, so the response may contain more items than the requested limit.

## 4. Headcount
The department summary counts employees from the employees collection based on their joining dates, rather than relying only on attendance logs. This includes eligible employees who have no attendance records.

## 5. Scaling
For 100 times more data, I would measure query performance with realistic data and consider precomputed daily summaries to reduce repeated aggregation work.