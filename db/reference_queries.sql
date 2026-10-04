/*
    Contract Query Agent - reference queries (SQL Server)
    Part 1: the core templates exactly as the agent will run them, for one contract.
    Part 2: a report applying the same logic to every contract; its output is
            the golden answer set in expected_answers.md.
        sqlcmd -S RAVICHANDRA -U sa -C -d Auto -i db\reference_queries.sql
*/
SET NOCOUNT ON;

DECLARE @seq        NVARCHAR(20) = N'CT-1001';
DECLARE @as_of_date DATE         = '2026-10-01';   -- agent default: CAST(GETDATE() AS DATE)
DECLARE @contract_id INT;

------------------------------------------------------------------------------
-- Part 1: templates
------------------------------------------------------------------------------
-- Resolve contract
SELECT @contract_id = Id FROM dbo.Contracts WHERE SequenceNumber = @seq;

-- Q1 status
SELECT Status, WorkflowStatus FROM dbo.Contracts WHERE Id = @contract_id;

-- Q2 next due date
SELECT TOP 1 rd.DueDate AS NextDueDate,
       SUM(rd.Amount) AS Amount, SUM(rd.TaxAmount) AS TaxAmount
FROM dbo.Receivables r
JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = @contract_id AND r.IsActive = 1
  AND rd.BillingStatus = 'NotInvoiced' AND rd.IsTaxAssessed = 0
GROUP BY rd.DueDate
ORDER BY rd.DueDate;

-- Q3 invoice amount
SELECT COUNT(pi.Id) AS InvoiceCount, pi.Currency,
       SUM(pi.InvoiceAmount) AS InvoiceAmount, SUM(pi.InvoiceTaxAmount) AS InvoiceTaxAmount
FROM dbo.LeaseFinances lf
JOIN dbo.LeaseFundings lfu ON lfu.LeaseFinanceId = lf.Id
JOIN dbo.PayableInvoices pi ON pi.Id = lfu.PayableInvoiceId
WHERE lf.ContractId = @contract_id
GROUP BY pi.Currency;

-- Q4 outstanding amount
SELECT COALESCE(SUM(rd.Balance), 0) AS OutstandingTotal
FROM dbo.Receivables r
JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
WHERE r.EntityType = 'CT' AND r.EntityId = @contract_id AND r.IsActive = 1
  AND r.DueDate <= @as_of_date
  AND rd.BillingStatus NOT IN ('Paid', 'Suppressed', 'Suspended')
  AND rd.Balance > 0;

------------------------------------------------------------------------------
-- Part 2: golden answers for all contracts
------------------------------------------------------------------------------
SELECT c.SequenceNumber,
       c.ContractType,
       COALESCE(c.Status, 'not yet commenced') AS Status,
       c.WorkflowStatus,
       nd.NextDueDate,
       nd.Amount + nd.TaxAmount             AS NextDueTotal,
       COALESCE(inv.InvoiceCount, 0)        AS InvoiceCount,
       inv.InvoiceAmount,
       inv.InvoiceTaxAmount,
       os.OutstandingTotal
FROM dbo.Contracts c
OUTER APPLY (
    SELECT TOP 1 rd.DueDate AS NextDueDate, SUM(rd.Amount) AS Amount, SUM(rd.TaxAmount) AS TaxAmount
    FROM dbo.Receivables r
    JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
    WHERE r.EntityType = 'CT' AND r.EntityId = c.Id AND r.IsActive = 1
      AND rd.BillingStatus = 'NotInvoiced' AND rd.IsTaxAssessed = 0
    GROUP BY rd.DueDate
    ORDER BY rd.DueDate
) nd
OUTER APPLY (
    SELECT COUNT(pi.Id) AS InvoiceCount,
           SUM(pi.InvoiceAmount) AS InvoiceAmount, SUM(pi.InvoiceTaxAmount) AS InvoiceTaxAmount
    FROM dbo.LeaseFinances lf
    JOIN dbo.LeaseFundings lfu ON lfu.LeaseFinanceId = lf.Id
    JOIN dbo.PayableInvoices pi ON pi.Id = lfu.PayableInvoiceId
    WHERE lf.ContractId = c.Id
    HAVING COUNT(pi.Id) > 0
) inv
OUTER APPLY (
    SELECT COALESCE(SUM(rd.Balance), 0) AS OutstandingTotal
    FROM dbo.Receivables r
    JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id
    WHERE r.EntityType = 'CT' AND r.EntityId = c.Id AND r.IsActive = 1
      AND r.DueDate <= @as_of_date
      AND rd.BillingStatus NOT IN ('Paid', 'Suppressed', 'Suspended')
      AND rd.Balance > 0
) os
ORDER BY c.SequenceNumber;
