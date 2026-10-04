"""Vetted SQL for contract resolution and the four core questions (spec: Business rules).
Parameters: :contract_id (resolved from the sequence number) and :as_of_date."""

RESOLVE_CONTRACT = """
SELECT Id, ContractType FROM dbo.Contracts WHERE SequenceNumber = :seq
"""

# The contract's customer PII, loaded into the session vault as known values so they are
# masked wherever they appear. Never sent to the LLM. SSN is deliberately excluded.
CUSTOMER_PROFILE = """
SELECT cu.FirstName, cu.LastName, cu.AddressLine1, cu.AddressLine2, cu.Zip, cu.Phone, cu.Email
FROM dbo.Customers cu JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id
WHERE lf.ContractId = :contract_id
UNION
SELECT cu.FirstName, cu.LastName, cu.AddressLine1, cu.AddressLine2, cu.Zip, cu.Phone, cu.Email
FROM dbo.Customers cu JOIN dbo.LoanFinances ln ON ln.CustomerId = cu.Id
WHERE ln.ContractId = :contract_id
"""

CORE_TEMPLATES: dict[str, str] = {
    "status": """
SELECT COALESCE(Status, 'Not yet commenced') AS Status, WorkflowStatus
FROM dbo.Contracts WHERE Id = :contract_id
""",
    "next_due_date": """
SELECT TOP 1 rd.DueDate AS NextDueDate,
       SUM(rd.Amount) AS Amount, SUM(rd.TaxAmount) AS TaxAmount
FROM dbo.Receivables r
JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1
  AND rd.BillingStatus = 'NotInvoiced' AND rd.IsTaxAssessed = 0
GROUP BY rd.DueDate
ORDER BY rd.DueDate
""",
    "invoice_amount": """
SELECT COUNT(pi.Id) AS InvoiceCount, pi.Currency,
       SUM(pi.InvoiceAmount) AS InvoiceAmount, SUM(pi.InvoiceTaxAmount) AS InvoiceTaxAmount
FROM dbo.LeaseFinances lf
JOIN dbo.LeaseFundings lfu ON lfu.LeaseFinanceId = lf.Id
JOIN dbo.PayableInvoices pi ON pi.Id = lfu.PayableInvoiceId
WHERE lf.ContractId = :contract_id
GROUP BY pi.Currency
""",
    "outstanding_amount": """
SELECT COALESCE(SUM(rd.Balance), 0) AS OutstandingTotal
FROM dbo.Receivables r
JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id AND r.IsActive = 1
  AND r.DueDate <= :as_of_date
  AND rd.BillingStatus NOT IN ('Paid', 'Suppressed', 'Suspended')
  AND rd.Balance > 0
""",
}
