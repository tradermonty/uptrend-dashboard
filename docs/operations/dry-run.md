# Dry-run collection and Excel import

`python collect.py --dry-run --scope all` fetches and validates Finviz responses without opening the target database. `--worksheet` and other scopes follow the same boundary. A Finviz API credential and network connection are still required outside tests; dry-run is not an offline mode. Existing collection date rules still apply.

`python import_excel.py export.xlsx --dry-run --db preview.db` reads and filters the workbook, reporting accepted row counts without opening the target database. Row filtering, sheet selection and accepted counts follow the same parsing logic as an actual import. Invalid sheets/rows keep the existing skip-and-warning policy; a reported count is not a promise that subsequent database validation or persistence will succeed.

Both previews leave absent targets absent, create no parent directories, and do not initialize, migrate, inspect or change existing target bytes/schema/indexes. They also work when the specified target is not a readable SQLite database because the target is unused. Neither command validates target permissions, schema, disk capacity, or readiness for a later real write.

## Collection exit statuses

| Mode | 0 | 1 | 2 |
|---|---|---|---|
| Bulk dry-run, any scope | Every attempted worksheet succeeded | All attempted worksheets failed, or setup failed | Some succeeded and some failed |
| Single worksheet dry-run | Succeeded | Failed, or setup failed | Unused |

Dry-run treats any industry failure as a failure, even below the live collection tolerance. Inspect both the status and summary/logs. Actual collection retains its existing 5% industry-failure tolerance and scope-dependent exit policy. HTTP sessions close on successful collection and failure exits. Excel parsing failures propagate; no database initialization occurs in dry-run.

No historical database or published CSV correction is performed by these changes.
