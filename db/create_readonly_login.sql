/*
    Contract Query Agent - read-only login for the agent (SQL Server)
    Run ONCE as sa, AFTER schema.sql and seed.sql (the SSN deny needs dbo.Customers).

    1. Replace <your-strong-password> below (12+ chars, mixed case, digit, symbol).
    2. Run it in SSMS, or:
           sqlcmd -S RAVICHANDRA -U sa -C -b -i db\create_readonly_login.sql
       (-b stops at the first error, so a missed placeholder halts everything)
    3. Do NOT commit this file with a real password in it.
*/
SET NOCOUNT ON;
GO

USE master;
DECLARE @pwd NVARCHAR(128) = N'<your-strong-password>';
IF @pwd = N'<your-strong-password>'
    THROW 50010, 'Replace <your-strong-password> with a real password before running this script.', 1;
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'agent_ro')
BEGIN
    DECLARE @sql NVARCHAR(MAX) = N'CREATE LOGIN agent_ro WITH PASSWORD = '
        + QUOTENAME(@pwd, '''') + N', DEFAULT_DATABASE = Auto, CHECK_POLICY = ON;';
    EXEC (@sql);
END
GO

USE Auto;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'agent_ro')
    CREATE USER agent_ro FOR LOGIN agent_ro;
ALTER ROLE db_datareader ADD MEMBER agent_ro;
-- Defence in depth: the agent can never read SSN, even if the SQL validator is bypassed
DENY SELECT ON dbo.Customers (SSN) TO agent_ro;
GO

-- Verification: first two succeed, last two must fail with a permission error
EXECUTE AS LOGIN = N'agent_ro';
SELECT TOP 1 SequenceNumber FROM dbo.Contracts;
SELECT TOP 1 FirstName FROM dbo.Customers;
BEGIN TRY
    SELECT TOP 1 SSN FROM dbo.Customers;
    PRINT 'FAIL: SSN was readable';
END TRY
BEGIN CATCH
    PRINT 'OK: SSN denied - ' + ERROR_MESSAGE();
END CATCH;
BEGIN TRY
    UPDATE dbo.Contracts SET Status = Status WHERE 1 = 0;
    PRINT 'FAIL: UPDATE was allowed';
END TRY
BEGIN CATCH
    PRINT 'OK: UPDATE denied - ' + ERROR_MESSAGE();
END CATCH;
REVERT;
GO
