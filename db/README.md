# Database scripts

SQL Server 2022, database `Auto`. Run from the project root, in this order:

| # | Script | Run as | What it does |
| --- | --- | --- | --- |
| 1 | `schema.sql` | sa | Drops and recreates the 8 tables (only these 8) |
| 2 | `seed.sql` | sa | Loads 12 contracts and 9 customers; fails if any modeling rule is broken |
| 3 | `create_readonly_login.sql` | sa | Creates `agent_ro` (read-only, no SSN). Edit the password first; run once |
| 4 | `reference_queries.sql` | any | Runs the core Q1–Q4 templates and prints the golden answers |

```powershell
sqlcmd -S RAVICHANDRA -U sa -C -b -d Auto -i db\schema.sql
sqlcmd -S RAVICHANDRA -U sa -C -b -d Auto -i db\seed.sql
sqlcmd -S RAVICHANDRA -U sa -C -b -i db\create_readonly_login.sql
sqlcmd -S RAVICHANDRA -U sa -C -b -d Auto -W -i db\reference_queries.sql
```

`sqlcmd` prompts for the password when `-P` is omitted. Steps 1–2 can be re-run any time to reset the test data.
Expected results: `expected_answers.md`.
