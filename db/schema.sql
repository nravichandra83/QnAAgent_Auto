/*
    Contract Query Agent - table schema (SQL Server)
    Target database: Auto
    Re-runnable: drops and recreates ONLY the 8 tables below.
    Run as an admin login (e.g. sa):
        sqlcmd -S RAVICHANDRA -U sa -C -d Auto -i db\schema.sql
*/
SET NOCOUNT ON;
GO

-- Drop in reverse dependency order
DROP TABLE IF EXISTS dbo.ReceivableDetails;
DROP TABLE IF EXISTS dbo.Receivables;
DROP TABLE IF EXISTS dbo.LeaseFundings;
DROP TABLE IF EXISTS dbo.PayableInvoices;
DROP TABLE IF EXISTS dbo.LeaseFinances;
DROP TABLE IF EXISTS dbo.LoanFinances;
DROP TABLE IF EXISTS dbo.Customers;
DROP TABLE IF EXISTS dbo.Contracts;
GO

CREATE TABLE dbo.Contracts (
    Id               INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Contracts PRIMARY KEY,
    SequenceNumber   NVARCHAR(20)  NOT NULL CONSTRAINT UQ_Contracts_SequenceNumber UNIQUE,
    Status           NVARCHAR(20)  NULL,          -- NULL until commenced
    WorkflowStatus   NVARCHAR(30)  NOT NULL,
    CommencementDate DATE          NULL,
    ContractType     NVARCHAR(10)  NOT NULL,
    CONSTRAINT CK_Contracts_Status
        CHECK (Status IN (N'Commenced', N'PaidOff', N'Restructure', N'Rebook')),
    CONSTRAINT CK_Contracts_WorkflowStatus
        CHECK (WorkflowStatus IN (N'Documents Submitted', N'Documents Revision', N'Submitted', N'Approved', N'Commenced')),
    CONSTRAINT CK_Contracts_ContractType
        CHECK (ContractType IN (N'Lease', N'Loan'))
);
GO

CREATE TABLE dbo.Customers (
    Id           INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Customers PRIMARY KEY,
    FirstName    NVARCHAR(100) NOT NULL,
    LastName     NVARCHAR(100) NULL,
    CustomerType NVARCHAR(20)  NOT NULL,
    AddressLine1 NVARCHAR(200) NULL,
    AddressLine2 NVARCHAR(200) NULL,
    Zip          NVARCHAR(10)  NULL,
    SSN          CHAR(11)      NULL,              -- PII: restricted, never selected by the agent
    Phone        NVARCHAR(20)  NULL,
    Email        NVARCHAR(200) NULL,
    CONSTRAINT CK_Customers_CustomerType CHECK (CustomerType IN (N'Individual', N'Business'))
);
GO

CREATE TABLE dbo.LeaseFinances (
    Id          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_LeaseFinances PRIMARY KEY,
    ContractId  INT           NOT NULL CONSTRAINT UQ_LeaseFinances_ContractId UNIQUE
                CONSTRAINT FK_LeaseFinances_Contracts REFERENCES dbo.Contracts (Id),
    Status      NVARCHAR(20)  NOT NULL,
    BookingDate DATE          NULL,
    DownPayment DECIMAL(18,2) NOT NULL CONSTRAINT DF_LeaseFinances_DownPayment DEFAULT (0),
    CustomerId  INT           NOT NULL
                CONSTRAINT FK_LeaseFinances_Customers REFERENCES dbo.Customers (Id)
);
GO

CREATE TABLE dbo.LoanFinances (
    Id          INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_LoanFinances PRIMARY KEY,
    ContractId  INT           NOT NULL CONSTRAINT UQ_LoanFinances_ContractId UNIQUE
                CONSTRAINT FK_LoanFinances_Contracts REFERENCES dbo.Contracts (Id),
    Status      NVARCHAR(20)  NOT NULL,
    BookingDate DATE          NULL,
    CustomerId  INT           NOT NULL
                CONSTRAINT FK_LoanFinances_Customers REFERENCES dbo.Customers (Id)
);
GO

CREATE TABLE dbo.PayableInvoices (
    Id               INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PayableInvoices PRIMARY KEY,
    InvoiceAmount    DECIMAL(18,2) NOT NULL,
    Status           NVARCHAR(20)  NOT NULL,
    InvoiceDate      DATE          NOT NULL,
    InvoiceTaxAmount DECIMAL(18,2) NOT NULL CONSTRAINT DF_PayableInvoices_Tax DEFAULT (0),
    Currency         CHAR(3)       NOT NULL CONSTRAINT DF_PayableInvoices_Currency DEFAULT ('USD')
);
GO

CREATE TABLE dbo.LeaseFundings (
    LeaseFinanceId   INT NOT NULL
                     CONSTRAINT FK_LeaseFundings_LeaseFinances REFERENCES dbo.LeaseFinances (Id),
    PayableInvoiceId INT NOT NULL
                     CONSTRAINT FK_LeaseFundings_PayableInvoices REFERENCES dbo.PayableInvoices (Id),
    CONSTRAINT PK_LeaseFundings PRIMARY KEY (LeaseFinanceId, PayableInvoiceId)
);
GO

CREATE TABLE dbo.Receivables (
    Id         INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Receivables PRIMARY KEY,
    EntityId   INT           NOT NULL,            -- Contracts.Id when EntityType = 'CT' (polymorphic, no FK)
    EntityType CHAR(2)       NOT NULL,
    Amount     DECIMAL(18,2) NOT NULL,            -- = SUM(ReceivableDetails.Amount)
    TaxAmount  DECIMAL(18,2) NOT NULL,            -- = SUM(ReceivableDetails.TaxAmount)
    DueDate    DATE          NOT NULL,
    IsActive   BIT           NOT NULL CONSTRAINT DF_Receivables_IsActive DEFAULT (1),
    CONSTRAINT CK_Receivables_EntityType CHECK (EntityType IN ('CT', 'SU'))
);
CREATE INDEX IX_Receivables_Entity ON dbo.Receivables (EntityType, EntityId, IsActive) INCLUDE (DueDate);
GO

CREATE TABLE dbo.ReceivableDetails (
    Id            INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ReceivableDetails PRIMARY KEY,
    ReceivableId  INT           NOT NULL
                  CONSTRAINT FK_ReceivableDetails_Receivables REFERENCES dbo.Receivables (Id),
    IsTaxAssessed BIT           NOT NULL CONSTRAINT DF_ReceivableDetails_IsTaxAssessed DEFAULT (0),
    BillingStatus NVARCHAR(20)  NOT NULL,
    DueDate       DATE          NOT NULL,
    Amount        DECIMAL(18,2) NOT NULL,
    TaxAmount     DECIMAL(18,2) NOT NULL CONSTRAINT DF_ReceivableDetails_TaxAmount DEFAULT (0),
    Balance       DECIMAL(18,2) NOT NULL,         -- unpaid part of Amount + TaxAmount; 0 when Paid
    CONSTRAINT CK_ReceivableDetails_BillingStatus
        CHECK (BillingStatus IN (N'Invoiced', N'NotInvoiced', N'Suppressed', N'Suspended', N'Paid')),
    CONSTRAINT CK_ReceivableDetails_Balance
        CHECK (Balance >= 0 AND Balance <= Amount + TaxAmount),
    CONSTRAINT CK_ReceivableDetails_PaidBalance
        CHECK (BillingStatus <> N'Paid' OR Balance = 0)
);
CREATE INDEX IX_ReceivableDetails_Receivable ON dbo.ReceivableDetails (ReceivableId, BillingStatus);
GO

PRINT 'Schema created: 8 tables.';
