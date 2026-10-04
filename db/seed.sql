/*
    Contract Query Agent - test data (SQL Server)
    12 contracts, 9 customers; dates fixed around the test as-of date 2026-10-01.
    All PII is synthetic: SSNs in the never-issued 900 range, example.com emails, 555-01xx phones.
    Re-runnable: clears the 8 tables, then inserts. Run after schema.sql:
        sqlcmd -S RAVICHANDRA -U sa -C -d Auto -i db\seed.sql
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

DELETE FROM dbo.ReceivableDetails;
DELETE FROM dbo.Receivables;
DELETE FROM dbo.LeaseFundings;
DELETE FROM dbo.PayableInvoices;
DELETE FROM dbo.LeaseFinances;
DELETE FROM dbo.LoanFinances;
DELETE FROM dbo.Customers;
DELETE FROM dbo.Contracts;

------------------------------------------------------------------------------
-- Contracts
------------------------------------------------------------------------------
SET IDENTITY_INSERT dbo.Contracts ON;
INSERT INTO dbo.Contracts (Id, SequenceNumber, Status, WorkflowStatus, CommencementDate, ContractType) VALUES
 ( 1, N'CT-1001', N'Commenced',   N'Commenced',           '2026-05-01', N'Lease'),  -- happy path
 ( 2, N'CT-1002', N'Commenced',   N'Commenced',           '2026-06-01', N'Lease'),  -- all past paid
 ( 3, N'CT-1003', N'Commenced',   N'Commenced',           '2026-04-15', N'Loan'),   -- suspended + past unbilled
 ( 4, N'CT-1004', N'PaidOff',     N'Commenced',           '2026-04-01', N'Loan'),   -- fully paid off
 ( 5, N'CT-1005', N'Restructure', N'Commenced',           '2026-03-01', N'Lease'),  -- inactive old schedule
 ( 6, N'CT-1006', N'Rebook',      N'Commenced',           '2026-07-01', N'Lease'),  -- 3 payable invoices
 ( 7, N'CT-1007', NULL,           N'Documents Submitted', NULL,         N'Lease'),  -- pre-commencement
 ( 8, N'CT-1008', N'Commenced',   N'Commenced',           '2026-08-01', N'Loan'),   -- tax-assessed detail
 ( 9, N'CT-1009', N'Commenced',   N'Commenced',           '2026-06-01', N'Lease'),  -- suppressed + suspended
 (10, N'CT-1010', N'Commenced',   N'Commenced',           '2026-07-01', N'Loan'),   -- SU receivables on same Id
 (11, N'CT-1011', N'Commenced',   N'Commenced',           '2026-07-01', N'Lease'),  -- partial payment
 (12, N'CT-1012', N'Commenced',   N'Documents Revision',  '2026-09-15', N'Lease');  -- no money data
SET IDENTITY_INSERT dbo.Contracts OFF;

------------------------------------------------------------------------------
-- Customers (synthetic PII)
------------------------------------------------------------------------------
SET IDENTITY_INSERT dbo.Customers ON;
INSERT INTO dbo.Customers (Id, FirstName, LastName, CustomerType, AddressLine1, AddressLine2, Zip, SSN, Phone, Email) VALUES
 (1, N'John',                N'Carter',   N'Individual', N'12 Maple Street',      N'Apt 4B',    N'30301', '900-12-3456', N'555-0101', N'john.carter@example.com'),
 (2, N'Northwind Logistics', N'LLC',      N'Business',   N'400 Harbor Blvd',      N'Suite 210', N'98101', '900-23-4567', N'555-0102', N'accounts@northwind.example.com'),
 (3, N'Maria',               N'Lopez',    N'Individual', N'78 Sunset Avenue',     NULL,         N'85001', '900-34-5678', N'555-0103', N'maria.lopez@example.com'),
 (4, N'Blue Ridge Farms',    N'Inc',      N'Business',   N'Route 9, Box 112',     NULL,         N'24001', '900-45-6789', N'555-0104', N'office@blueridge.example.com'),
 (5, N'Priya',               N'Nair',     N'Individual', N'5 Lakeview Court',     NULL,         N'60601', '900-56-7890', N'555-0105', N'priya.nair@example.com'),
 (6, N'David',               N'O''Connor', N'Individual', N'221 Elm Road',        N'Unit 7',    N'02101', '900-67-8901', N'555-0106', N'david.oconnor@example.com'),
 (7, N'Emily',               N'Chen',     N'Individual', N'19 Cedar Lane',        NULL,         N'94101', '900-78-9012', N'555-0107', N'emily.chen@example.com'),
 (8, N'Summit Construction', N'Co',       N'Business',   N'900 Industrial Pkwy',  NULL,         N'80201', '900-89-0123', N'555-0108', N'billing@summit.example.com'),
 (9, N'Samuel',              N'Okafor',   N'Individual', N'63 Birch Way',         NULL,         N'77001', '900-90-1234', N'555-0109', N'samuel.okafor@example.com');
SET IDENTITY_INSERT dbo.Customers OFF;

------------------------------------------------------------------------------
-- Finance records: one per contract, by ContractType
------------------------------------------------------------------------------
SET IDENTITY_INSERT dbo.LeaseFinances ON;
INSERT INTO dbo.LeaseFinances (Id, ContractId, Status, BookingDate, DownPayment, CustomerId) VALUES
 (1,  1, N'Commenced', '2026-04-20', 5000.00, 1),
 (2,  2, N'Commenced', '2026-05-25', 12000.00, 2),
 (3,  5, N'Commenced', '2026-02-20', 6000.00, 4),
 (4,  6, N'Commenced', '2026-06-18', 7000.00, 2),
 (5,  7, N'Pending',   NULL,         0.00,    5),
 (6,  9, N'Commenced', '2026-05-22', 5200.00, 7),
 (7, 11, N'Commenced', '2026-06-24', 7000.00, 3),
 (8, 12, N'Commenced', '2026-09-10', 3000.00, 9);
SET IDENTITY_INSERT dbo.LeaseFinances OFF;

SET IDENTITY_INSERT dbo.LoanFinances ON;
INSERT INTO dbo.LoanFinances (Id, ContractId, Status, BookingDate, CustomerId) VALUES
 (1,  3, N'Commenced', '2026-04-10', 3),
 (2,  4, N'PaidOff',   '2026-03-25', 1),
 (3,  8, N'Commenced', '2026-07-28', 6),
 (4, 10, N'Commenced', '2026-06-26', 8);
SET IDENTITY_INSERT dbo.LoanFinances OFF;

------------------------------------------------------------------------------
-- Payable invoices and lease fundings (lease contracts only)
------------------------------------------------------------------------------
SET IDENTITY_INSERT dbo.PayableInvoices ON;
INSERT INTO dbo.PayableInvoices (Id, InvoiceAmount, Status, InvoiceDate, InvoiceTaxAmount, Currency) VALUES
 (1,  45000.00, N'Paid', '2026-04-25', 3600.00, 'USD'),  -- CT-1001
 (2, 120000.00, N'Paid', '2026-05-28', 9600.00, 'USD'),  -- CT-1002
 (3,  60000.00, N'Paid', '2026-02-26', 4800.00, 'USD'),  -- CT-1005
 (4,  30000.00, N'Paid', '2026-06-20', 2400.00, 'USD'),  -- CT-1006
 (5,  25000.00, N'Paid', '2026-06-24', 2000.00, 'USD'),  -- CT-1006
 (6,  15000.00, N'Paid', '2026-06-29', 1200.00, 'USD'),  -- CT-1006
 (7,  52000.00, N'Paid', '2026-05-27', 4160.00, 'USD'),  -- CT-1009
 (8,  70000.00, N'Paid', '2026-06-26', 5600.00, 'USD');  -- CT-1011
SET IDENTITY_INSERT dbo.PayableInvoices OFF;

INSERT INTO dbo.LeaseFundings (LeaseFinanceId, PayableInvoiceId) VALUES
 (1, 1), (2, 2), (3, 3), (4, 4), (4, 5), (4, 6), (6, 7), (7, 8);

------------------------------------------------------------------------------
-- Receivables + details
-- Details are staged first; each receivable's Amount/TaxAmount is then
-- computed as the SUM of its details, so the aggregation rule always holds.
------------------------------------------------------------------------------
DECLARE @r TABLE (Id INT PRIMARY KEY, EntityId INT, EntityType CHAR(2), DueDate DATE, IsActive BIT);
DECLARE @d TABLE (ReceivableId INT, IsTaxAssessed BIT, BillingStatus NVARCHAR(20), DueDate DATE,
                  Amount DECIMAL(18,2), TaxAmount DECIMAL(18,2), Balance DECIMAL(18,2));

INSERT INTO @r (Id, EntityId, EntityType, DueDate, IsActive) VALUES
 -- CT-1001: rent 1000 + tax 80
 ( 1,  1, 'CT', '2026-05-01', 1), ( 2,  1, 'CT', '2026-06-01', 1), ( 3,  1, 'CT', '2026-07-01', 1),
 ( 4,  1, 'CT', '2026-08-01', 1), ( 5,  1, 'CT', '2026-09-01', 1), ( 6,  1, 'CT', '2026-10-01', 1),
 ( 7,  1, 'CT', '2026-11-01', 1), ( 8,  1, 'CT', '2026-12-01', 1),
 -- CT-1002: rent 2500 + tax 200
 ( 9,  2, 'CT', '2026-06-01', 1), (10,  2, 'CT', '2026-07-01', 1), (11,  2, 'CT', '2026-08-01', 1),
 (12,  2, 'CT', '2026-09-01', 1), (13,  2, 'CT', '2026-10-01', 1), (14,  2, 'CT', '2026-11-01', 1),
 (15,  2, 'CT', '2026-12-01', 1),
 -- CT-1003: loan payment 750, no tax
 (16,  3, 'CT', '2026-04-15', 1), (17,  3, 'CT', '2026-05-15', 1), (18,  3, 'CT', '2026-06-15', 1),
 (19,  3, 'CT', '2026-07-15', 1), (20,  3, 'CT', '2026-08-15', 1), (21,  3, 'CT', '2026-09-15', 1),
 (22,  3, 'CT', '2026-10-15', 1), (23,  3, 'CT', '2026-11-15', 1),
 -- CT-1004: loan payment 500, all paid
 (24,  4, 'CT', '2026-04-01', 1), (25,  4, 'CT', '2026-05-01', 1), (26,  4, 'CT', '2026-06-01', 1),
 (27,  4, 'CT', '2026-07-01', 1), (28,  4, 'CT', '2026-08-01', 1), (29,  4, 'CT', '2026-09-01', 1),
 -- CT-1005: old schedule 1200 + 96 (inactive from July), new schedule 900 + 72
 (30,  5, 'CT', '2026-03-01', 1), (31,  5, 'CT', '2026-04-01', 1), (32,  5, 'CT', '2026-05-01', 1),
 (33,  5, 'CT', '2026-06-01', 1),
 (34,  5, 'CT', '2026-07-01', 0), (35,  5, 'CT', '2026-08-01', 0), (36,  5, 'CT', '2026-09-01', 0),
 (37,  5, 'CT', '2026-10-01', 0), (38,  5, 'CT', '2026-11-01', 0),
 (39,  5, 'CT', '2026-07-01', 1), (40,  5, 'CT', '2026-08-01', 1), (41,  5, 'CT', '2026-09-01', 1),
 (42,  5, 'CT', '2026-10-01', 1), (43,  5, 'CT', '2026-11-01', 1), (44,  5, 'CT', '2026-12-01', 1),
 -- CT-1006: rent 1800 + tax 144
 (45,  6, 'CT', '2026-07-01', 1), (46,  6, 'CT', '2026-08-01', 1), (47,  6, 'CT', '2026-09-01', 1),
 (48,  6, 'CT', '2026-10-01', 1), (49,  6, 'CT', '2026-11-01', 1), (50,  6, 'CT', '2026-12-01', 1),
 -- CT-1008: loan payment 1500, plus a tax-assessed charge on 2026-10-20
 (51,  8, 'CT', '2026-08-01', 1), (52,  8, 'CT', '2026-09-01', 1), (53,  8, 'CT', '2026-10-01', 1),
 (54,  8, 'CT', '2026-10-20', 1), (55,  8, 'CT', '2026-11-01', 1), (56,  8, 'CT', '2026-12-01', 1),
 -- CT-1009: rent 1100 + tax 88
 (57,  9, 'CT', '2026-06-01', 1), (58,  9, 'CT', '2026-07-01', 1), (59,  9, 'CT', '2026-08-01', 1),
 (60,  9, 'CT', '2026-09-01', 1), (61,  9, 'CT', '2026-10-01', 1), (62,  9, 'CT', '2026-11-01', 1),
 -- CT-1010: loan payment 2000, plus two SU (sundry) receivables with EntityId = 10
 (63, 10, 'CT', '2026-07-01', 1), (64, 10, 'CT', '2026-08-01', 1), (65, 10, 'CT', '2026-09-01', 1),
 (66, 10, 'CT', '2026-10-01', 1), (67, 10, 'CT', '2026-11-01', 1),
 (68, 10, 'SU', '2026-08-15', 1), (69, 10, 'SU', '2026-10-10', 1),
 -- CT-1011: rent 1500 + tax 120; Aug receivable has two details, one partly paid
 (70, 11, 'CT', '2026-07-01', 1), (71, 11, 'CT', '2026-08-01', 1), (72, 11, 'CT', '2026-09-01', 1),
 (73, 11, 'CT', '2026-10-01', 1), (74, 11, 'CT', '2026-11-01', 1);

INSERT INTO @d (ReceivableId, IsTaxAssessed, BillingStatus, DueDate, Amount, TaxAmount, Balance) VALUES
 -- CT-1001
 ( 1, 0, N'Paid',        '2026-05-01', 1000, 80, 0),
 ( 2, 0, N'Paid',        '2026-06-01', 1000, 80, 0),
 ( 3, 0, N'Paid',        '2026-07-01', 1000, 80, 0),
 ( 4, 0, N'Paid',        '2026-08-01', 1000, 80, 0),
 ( 5, 0, N'Invoiced',    '2026-09-01', 1000, 80, 1080),
 ( 6, 0, N'Invoiced',    '2026-10-01', 1000, 80, 1080),   -- due exactly on as-of date: counts
 ( 7, 0, N'NotInvoiced', '2026-11-01', 1000, 80, 1080),
 ( 8, 0, N'NotInvoiced', '2026-12-01', 1000, 80, 1080),
 -- CT-1002
 ( 9, 0, N'Paid',        '2026-06-01', 2500, 200, 0),
 (10, 0, N'Paid',        '2026-07-01', 2500, 200, 0),
 (11, 0, N'Paid',        '2026-08-01', 2500, 200, 0),
 (12, 0, N'Paid',        '2026-09-01', 2500, 200, 0),
 (13, 0, N'Paid',        '2026-10-01', 2500, 200, 0),
 (14, 0, N'NotInvoiced', '2026-11-01', 2500, 200, 2700),
 (15, 0, N'NotInvoiced', '2026-12-01', 2500, 200, 2700),
 -- CT-1003
 (16, 0, N'Paid',        '2026-04-15', 750, 0, 0),
 (17, 0, N'Paid',        '2026-05-15', 750, 0, 0),
 (18, 0, N'Paid',        '2026-06-15', 750, 0, 0),
 (19, 0, N'Suspended',   '2026-07-15', 750, 0, 750),      -- excluded from outstanding
 (20, 0, N'Invoiced',    '2026-08-15', 750, 0, 750),
 (21, 0, N'NotInvoiced', '2026-09-15', 750, 0, 750),      -- billing lag: past but unbilled
 (22, 0, N'NotInvoiced', '2026-10-15', 750, 0, 750),
 (23, 0, N'NotInvoiced', '2026-11-15', 750, 0, 750),
 -- CT-1004
 (24, 0, N'Paid',        '2026-04-01', 500, 0, 0),
 (25, 0, N'Paid',        '2026-05-01', 500, 0, 0),
 (26, 0, N'Paid',        '2026-06-01', 500, 0, 0),
 (27, 0, N'Paid',        '2026-07-01', 500, 0, 0),
 (28, 0, N'Paid',        '2026-08-01', 500, 0, 0),
 (29, 0, N'Paid',        '2026-09-01', 500, 0, 0),
 -- CT-1005 old schedule (30-33 active and paid; 34-38 inactive and must be ignored)
 (30, 0, N'Paid',        '2026-03-01', 1200, 96, 0),
 (31, 0, N'Paid',        '2026-04-01', 1200, 96, 0),
 (32, 0, N'Paid',        '2026-05-01', 1200, 96, 0),
 (33, 0, N'Paid',        '2026-06-01', 1200, 96, 0),
 (34, 0, N'Invoiced',    '2026-07-01', 1200, 96, 1296),
 (35, 0, N'Invoiced',    '2026-08-01', 1200, 96, 1296),
 (36, 0, N'Invoiced',    '2026-09-01', 1200, 96, 1296),
 (37, 0, N'NotInvoiced', '2026-10-01', 1200, 96, 1296),
 (38, 0, N'NotInvoiced', '2026-11-01', 1200, 96, 1296),
 -- CT-1005 new schedule
 (39, 0, N'Paid',        '2026-07-01', 900, 72, 0),
 (40, 0, N'Paid',        '2026-08-01', 900, 72, 0),
 (41, 0, N'Invoiced',    '2026-09-01', 900, 72, 972),
 (42, 0, N'Invoiced',    '2026-10-01', 900, 72, 972),
 (43, 0, N'NotInvoiced', '2026-11-01', 900, 72, 972),
 (44, 0, N'NotInvoiced', '2026-12-01', 900, 72, 972),
 -- CT-1006
 (45, 0, N'Paid',        '2026-07-01', 1800, 144, 0),
 (46, 0, N'Paid',        '2026-08-01', 1800, 144, 0),
 (47, 0, N'Paid',        '2026-09-01', 1800, 144, 0),
 (48, 0, N'Invoiced',    '2026-10-01', 1800, 144, 1944),
 (49, 0, N'NotInvoiced', '2026-11-01', 1800, 144, 1944),
 (50, 0, N'NotInvoiced', '2026-12-01', 1800, 144, 1944),
 -- CT-1008
 (51, 0, N'Paid',        '2026-08-01', 1500, 0, 0),
 (52, 0, N'Paid',        '2026-09-01', 1500, 0, 0),
 (53, 0, N'Invoiced',    '2026-10-01', 1500, 0, 1500),
 (54, 1, N'NotInvoiced', '2026-10-20', 250, 20, 270),     -- tax-assessed: next due date must skip it
 (55, 0, N'NotInvoiced', '2026-11-01', 1500, 0, 1500),
 (56, 0, N'NotInvoiced', '2026-12-01', 1500, 0, 1500),
 -- CT-1009
 (57, 0, N'Paid',        '2026-06-01', 1100, 88, 0),
 (58, 0, N'Suppressed',  '2026-07-01', 1100, 88, 1188),   -- excluded from outstanding
 (59, 0, N'Suspended',   '2026-08-01', 1100, 88, 1188),   -- excluded from outstanding
 (60, 0, N'Invoiced',    '2026-09-01', 1100, 88, 1188),
 (61, 0, N'Invoiced',    '2026-10-01', 1100, 88, 1188),
 (62, 0, N'NotInvoiced', '2026-11-01', 1100, 88, 1188),
 -- CT-1010
 (63, 0, N'Paid',        '2026-07-01', 2000, 0, 0),
 (64, 0, N'Paid',        '2026-08-01', 2000, 0, 0),
 (65, 0, N'Invoiced',    '2026-09-01', 2000, 0, 2000),
 (66, 0, N'Invoiced',    '2026-10-01', 2000, 0, 2000),
 (67, 0, N'NotInvoiced', '2026-11-01', 2000, 0, 2000),
 (68, 0, N'Invoiced',    '2026-08-15', 300, 24, 324),     -- SU: must not count for the contract
 (69, 0, N'NotInvoiced', '2026-10-10', 150, 12, 162),     -- SU: must not become next due date
 -- CT-1011
 (70, 0, N'Paid',        '2026-07-01', 1500, 120, 0),
 (71, 0, N'Paid',        '2026-08-01', 1000, 80, 0),
 (71, 0, N'Invoiced',    '2026-08-01', 500, 40, 240),     -- partly paid: 300 of 540 received
 (72, 0, N'Invoiced',    '2026-09-01', 1500, 120, 1620),
 (73, 0, N'Invoiced',    '2026-10-01', 1500, 120, 1620),
 (74, 0, N'NotInvoiced', '2026-11-01', 1500, 120, 1620);

SET IDENTITY_INSERT dbo.Receivables ON;
INSERT INTO dbo.Receivables (Id, EntityId, EntityType, Amount, TaxAmount, DueDate, IsActive)
SELECT r.Id, r.EntityId, r.EntityType, SUM(d.Amount), SUM(d.TaxAmount), r.DueDate, r.IsActive
FROM @r r
JOIN @d d ON d.ReceivableId = r.Id
GROUP BY r.Id, r.EntityId, r.EntityType, r.DueDate, r.IsActive;
SET IDENTITY_INSERT dbo.Receivables OFF;

INSERT INTO dbo.ReceivableDetails (ReceivableId, IsTaxAssessed, BillingStatus, DueDate, Amount, TaxAmount, Balance)
SELECT ReceivableId, IsTaxAssessed, BillingStatus, DueDate, Amount, TaxAmount, Balance
FROM @d
ORDER BY ReceivableId;

------------------------------------------------------------------------------
-- Integrity checks: fail the whole seed if any modeling rule is broken
------------------------------------------------------------------------------
IF EXISTS (SELECT 1 FROM @r r WHERE NOT EXISTS (SELECT 1 FROM @d d WHERE d.ReceivableId = r.Id))
    THROW 50001, 'Seed check failed: a staged receivable has no details.', 1;

IF EXISTS (
    SELECT 1 FROM dbo.Receivables r
    JOIN (SELECT ReceivableId, SUM(Amount) AS A, SUM(TaxAmount) AS T
          FROM dbo.ReceivableDetails GROUP BY ReceivableId) d ON d.ReceivableId = r.Id
    WHERE r.Amount <> d.A OR r.TaxAmount <> d.T)
    THROW 50002, 'Seed check failed: Receivables amounts do not equal the sum of their details.', 1;

IF EXISTS (
    SELECT 1 FROM dbo.Contracts c
    WHERE (c.ContractType = N'Lease' AND (NOT EXISTS (SELECT 1 FROM dbo.LeaseFinances lf WHERE lf.ContractId = c.Id)
                                          OR EXISTS (SELECT 1 FROM dbo.LoanFinances ln WHERE ln.ContractId = c.Id)))
       OR (c.ContractType = N'Loan'  AND (NOT EXISTS (SELECT 1 FROM dbo.LoanFinances ln WHERE ln.ContractId = c.Id)
                                          OR EXISTS (SELECT 1 FROM dbo.LeaseFinances lf WHERE lf.ContractId = c.Id))))
    THROW 50003, 'Seed check failed: a contract does not have exactly one finance record matching its type.', 1;

IF EXISTS (SELECT 1 FROM dbo.Receivables r
           WHERE r.EntityType = 'CT' AND NOT EXISTS (SELECT 1 FROM dbo.Contracts c WHERE c.Id = r.EntityId))
    THROW 50004, 'Seed check failed: a CT receivable points to a missing contract.', 1;

COMMIT TRANSACTION;

SELECT 'Contracts' AS TableName, COUNT(*) AS Rows FROM dbo.Contracts
UNION ALL SELECT 'Customers',         COUNT(*) FROM dbo.Customers
UNION ALL SELECT 'LeaseFinances',     COUNT(*) FROM dbo.LeaseFinances
UNION ALL SELECT 'LoanFinances',      COUNT(*) FROM dbo.LoanFinances
UNION ALL SELECT 'PayableInvoices',   COUNT(*) FROM dbo.PayableInvoices
UNION ALL SELECT 'LeaseFundings',     COUNT(*) FROM dbo.LeaseFundings
UNION ALL SELECT 'Receivables',       COUNT(*) FROM dbo.Receivables
UNION ALL SELECT 'ReceivableDetails', COUNT(*) FROM dbo.ReceivableDetails;
