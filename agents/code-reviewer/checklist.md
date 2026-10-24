# Review checklist

## Correctness
- Does each new branch handle the empty / missing / error case?
- Does the code raise or return errors, and not hide them (bare `except`, empty `catch`)?
- Loops: off-by-one errors, changes to a collection during iteration, termination.
- Dates and times: time zones, daylight saving time, inclusive vs exclusive ranges.
- Money and counts: integers or decimals. Never use floats for currency.
- Concurrency: shared state, two requests at the same time, retries that apply two times.

## Security
- User input that gets to SQL, shell, file paths, HTML or URLs without escaping or
  validation.
- Authorization: can user A read or change the data of user B through this path?
- Secrets, tokens or keys that are committed in code, logs or error messages.
- New dependencies: are they maintained, licensed, and really necessary?

## Data
- Migrations: are they reversible? Do they lock a big table? Defaults for existing rows?
- Deletes: soft or hard? Do cascades remove more than intended?

## APIs
- Changes that break request/response shapes, status codes or URLs.
- Pagination and limits on each thing that can grow.

## Tests
- Is there a test for the changed behaviour, and also for the failure path?
- Do the tests assert results, not only that the code ran?
