"""Schema card and prompts sent to the LLM. No row data appears here."""

SCHEMA_CARD = """\
Database: SQL Server (T-SQL). All tables are in schema dbo.

Tables (columns):
- Contracts (Id INT PK, SequenceNumber NVARCHAR unique, Status NVARCHAR NULL, WorkflowStatus NVARCHAR,
  CommencementDate DATE NULL, ContractType NVARCHAR)
- Customers (Id INT PK, FirstName [PII], LastName [PII], CustomerType, AddressLine1 [PII], AddressLine2 [PII],
  Zip [PII], SSN [RESTRICTED - never select], Phone [PII], Email [PII])
- LeaseFinances (Id INT PK, ContractId -> Contracts.Id, Status, BookingDate DATE, DownPayment DECIMAL,
  CustomerId -> Customers.Id)                        -- exists only when ContractType = 'Lease'
- LoanFinances (Id INT PK, ContractId -> Contracts.Id, Status, BookingDate DATE,
  CustomerId -> Customers.Id)                        -- exists only when ContractType = 'Loan'
- PayableInvoices (Id INT PK, InvoiceAmount DECIMAL, Status, InvoiceDate DATE, InvoiceTaxAmount DECIMAL, Currency)
- LeaseFundings (LeaseFinanceId -> LeaseFinances.Id, PayableInvoiceId -> PayableInvoices.Id)  -- bridge table
- Receivables (Id INT PK, EntityId, EntityType, Amount DECIMAL, TaxAmount DECIMAL, DueDate DATE, IsActive BIT)
  -- EntityId = Contracts.Id only when EntityType = 'CT'
- ReceivableDetails (Id INT PK, ReceivableId -> Receivables.Id, IsTaxAssessed BIT, BillingStatus, DueDate DATE,
  Amount DECIMAL, TaxAmount DECIMAL, Balance DECIMAL)  -- Balance = unpaid part of Amount + TaxAmount

Enumerations:
- Contracts.Status: Commenced, PaidOff, Restructure, Rebook (NULL = not yet commenced)
- Contracts.WorkflowStatus: Documents Submitted, Documents Revision, Submitted, Approved, Commenced
- Contracts.ContractType: Lease, Loan
- Customers.CustomerType: Individual, Business
- Receivables.EntityType: CT (contract), SU (sundry - never include)
- ReceivableDetails.BillingStatus: Invoiced, NotInvoiced, Suppressed, Suspended, Paid

Business rules:
- Contract receivables: Receivables r WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1.
- Receivables.Amount/TaxAmount are sums of their details; prefer aggregating ReceivableDetails.
- Outstanding = SUM(ReceivableDetails.Balance) for receivables due on or before :as_of_date, excluding
  BillingStatus Paid, Suppressed and Suspended.
- The customer is reached via LeaseFinances (leases) or LoanFinances (loans), never directly from Contracts.
- Payable invoices are reached only via LeaseFundings -> LeaseFinances; loans have none.
"""

FEW_SHOTS = """\
Q: When did the contract commence?
SQL: SELECT CommencementDate FROM dbo.Contracts WHERE Id = :contract_id

Q: Who is the customer?
SQL: SELECT cu.FirstName, cu.LastName, cu.CustomerType
FROM dbo.Customers cu JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id
WHERE lf.ContractId = :contract_id
UNION
SELECT cu.FirstName, cu.LastName, cu.CustomerType
FROM dbo.Customers cu JOIN dbo.LoanFinances ln ON ln.CustomerId = cu.Id
WHERE ln.ContractId = :contract_id

Q: How many receivables have been paid?
SQL: SELECT COUNT(DISTINCT r.Id) AS PaidReceivables
FROM dbo.Receivables r JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1 AND rd.BillingStatus = 'Paid'

Q: List the overdue receivables.
SQL: SELECT r.DueDate, SUM(rd.Balance) AS Balance
FROM dbo.Receivables r JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1
  AND r.DueDate <= :as_of_date AND rd.BillingStatus NOT IN ('Paid', 'Suppressed', 'Suspended') AND rd.Balance > 0
GROUP BY r.DueDate ORDER BY r.DueDate

Q: When was the last payment due?
SQL: SELECT MAX(r.DueDate) AS LastDueDate
FROM dbo.Receivables r
WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1 AND r.DueDate <= :as_of_date

Q: What was the down payment?
SQL: SELECT DownPayment FROM dbo.LeaseFinances WHERE ContractId = :contract_id
"""

CLASSIFY_SYSTEM = """\
You route questions about one lease/loan contract. Pick exactly one intent:
- status: the contract's status or workflow status
- next_due_date: when the next payment/receivable is due (the next unbilled due date)
- invoice_amount: the TOTAL payable invoice amount funded for the contract (not the largest,
  smallest, a list, dates or any single invoice - those are adhoc)
- outstanding_amount: how much is outstanding / overdue / owed as of today
- adhoc: anything else (dates, customer, payment history, counts, lists, etc.)
Use the conversation so far to resolve follow-ups such as "and the tax?".
"""

GENERATE_SQL_SYSTEM = f"""\
You write one T-SQL SELECT that answers a question about a single contract.

{SCHEMA_CARD}
Hard rules:
- Every SELECT (including each UNION branch, subquery and CTE) that reads a table must filter a
  contract key with '=': Contracts.Id, LeaseFinances.ContractId, LoanFinances.ContractId or
  Receivables.EntityId (= :contract_id), and reach other tables only through key joins
  (e.g. LeaseFinances.CustomerId = Customers.Id). Qualify every column with a table alias.
- Receivables always need r.EntityType = 'CT'.
- Values like <PERSON_1> or <EMAIL_1> are masked placeholders, not real data; never put them in SQL.
- Use :as_of_date for "today" / "as of now"; never GETDATE().
- One SELECT statement only. No INSERT/UPDATE/DELETE/DDL/EXEC, no SELECT *, no OR (use IN).
- Never select Customers.SSN. Select PII columns only when the question asks for them.
- Use TOP n instead of LIMIT. Prefer aggregates over returning many rows.

Examples:
{FEW_SHOTS}"""

COMPOSE_SYSTEM = """\
You answer a user's question about contract {sequence_number} using only the query result provided.
Rules:
- Be brief: one to three sentences.
- Use only figures present in the result; never invent or estimate values.
- If the result is empty or all values are null, say plainly that there is no such data for this contract.
- Format money as 1,234.56 (with the currency if given) and dates as YYYY-MM-DD.
- "As of" date for this answer: {as_of_date}.
- Placeholders like <PERSON_1> are masked values; repeat them exactly as written.
"""
