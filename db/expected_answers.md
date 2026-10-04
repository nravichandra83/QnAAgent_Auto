# Expected answers (golden set)

As-of date: **2026-10-01**. Produced by `reference_queries.sql` Part 2 against `seed.sql`, and checked by hand.
Amounts are USD. "Next due" is amount + tax for that date. "Outstanding" is the total Balance (amount + tax).

| Seq no. | Type | Q1 Status | Q2 Next due | Q3 Invoices (count / amount / tax) | Q4 Outstanding | Wrong answer if the rule is broken |
| --- | --- | --- | --- | --- | --- | --- |
| CT-1001 | Lease | Commenced (Commenced) | 2026-11-01, 1,080.00 | 1 / 45,000.00 / 3,600.00 | 2,160.00 | 1,080.00 if `DueDate <= as-of` becomes `<` (10-01 boundary) |
| CT-1002 | Lease | Commenced (Commenced) | 2026-11-01, 2,700.00 | 1 / 120,000.00 / 9,600.00 | 0.00 | Non-zero if Paid lines are counted |
| CT-1003 | Loan | Commenced (Commenced) | 2026-09-15, 750.00 | none (loan) | 1,500.00 | 2,250.00 if Suspended counted; next due 10-15 if past dates are filtered out |
| CT-1004 | Loan | PaidOff (Commenced) | none | none (loan) | 0.00 | — |
| CT-1005 | Lease | Restructure (Commenced) | 2026-11-01, 972.00 | 1 / 60,000.00 / 4,800.00 | 1,944.00 | 7,128.00 outstanding and next due 10-01 if inactive receivables are counted |
| CT-1006 | Lease | Rebook (Commenced) | 2026-11-01, 1,944.00 | 3 / 70,000.00 / 5,600.00 | 1,944.00 | Q3 shows one invoice if fundings are not summed |
| CT-1007 | Lease | not yet commenced (Documents Submitted) | none | none | 0.00 | — |
| CT-1008 | Loan | Commenced (Commenced) | 2026-11-01, 1,500.00 | none (loan) | 1,500.00 | Next due 2026-10-20 if IsTaxAssessed is ignored |
| CT-1009 | Lease | Commenced (Commenced) | 2026-11-01, 1,188.00 | 1 / 52,000.00 / 4,160.00 | 2,376.00 | 4,752.00 if Suppressed and Suspended are counted |
| CT-1010 | Loan | Commenced (Commenced) | 2026-11-01, 2,000.00 | none (loan) | 4,000.00 | 4,324.00 outstanding / next due 10-10 if SU receivables leak in |
| CT-1011 | Lease | Commenced (Commenced) | 2026-11-01, 1,620.00 | 1 / 70,000.00 / 5,600.00 | 3,480.00 | 3,780.00 if Amount + Tax is used instead of Balance |
| CT-1012 | Lease | Commenced (Documents Revision) | none | none | 0.00 | — |

## Customers (for PII-masking tests)

All values are synthetic. The PII-leak test fails if any of these strings appears in an LLM payload.

| Id | Name | Type | Contracts |
| --- | --- | --- | --- |
| 1 | John Carter | Individual | CT-1001, CT-1004 |
| 2 | Northwind Logistics LLC | Business | CT-1002, CT-1006 |
| 3 | Maria Lopez | Individual | CT-1003, CT-1011 |
| 4 | Blue Ridge Farms Inc | Business | CT-1005 |
| 5 | Priya Nair | Individual | CT-1007 |
| 6 | David O'Connor | Individual | CT-1008 |
| 7 | Emily Chen | Individual | CT-1009 |
| 8 | Summit Construction Co | Business | CT-1010 |
| 9 | Samuel Okafor | Individual | CT-1012 |
