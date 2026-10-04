import pytest

from agent.prompts import FEW_SHOTS
from agent.templates import CORE_TEMPLATES
from agent.validator import used_params, validate_sql

FEW_SHOT_SQL = [block.split("SQL:", 1)[1].strip() for block in FEW_SHOTS.strip().split("\n\n")]


@pytest.mark.parametrize("sql", list(CORE_TEMPLATES.values()) + FEW_SHOT_SQL)
def test_vetted_queries_pass(sql):
    assert validate_sql(sql) == []


@pytest.mark.parametrize("sql, fragment", [
    ("", "empty"),
    ("SELEC Id FRM dbo.Contracts", "parse"),
    ("SELECT Id FROM dbo.Contracts WHERE Id = :contract_id; DROP TABLE dbo.Contracts", "one statement"),
    ("UPDATE dbo.Contracts SET Status = 'PaidOff' WHERE Id = :contract_id", "SELECT"),
    ("DELETE FROM dbo.Receivables WHERE EntityId = :contract_id", "SELECT"),
    ("EXEC xp_cmdshell 'dir'", "SELECT"),
    ("SELECT Id INTO dbo.Stolen FROM dbo.Contracts WHERE Id = :contract_id", "INTO"),
    ("SELECT name FROM sys.tables WHERE object_id = :contract_id", "outside dbo"),
    ("SELECT Id FROM dbo.Users WHERE Id = :contract_id", "not in the allowed schema"),
    ("SELECT Id FROM OtherDb.dbo.Contracts WHERE Id = :contract_id", "outside dbo"),
    ("SELECT cu.SSN FROM dbo.Customers cu JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id "
     "WHERE lf.ContractId = :contract_id", "restricted"),
    ("SELECT * FROM dbo.Contracts WHERE Id = :contract_id", "SELECT *"),
    ("SELECT Id FROM dbo.Contracts WHERE Id = :contract_id OR 1 = 1", "OR"),
    ("SELECT Id, SequenceNumber FROM dbo.Contracts", "current contract"),
    ("SELECT Id FROM dbo.Contracts WHERE Id > :contract_id", "current contract"),
    ("SELECT Id FROM dbo.Contracts WHERE Id = :contract_id AND Status = :status", "Unknown parameters"),
    ("SELECT x.a FROM OPENROWSET('SQLNCLI', 'srv', 'SELECT 1') x WHERE x.a = :contract_id", "not allowed"),
    # contract scoping: each of these would return rows of other contracts or customers
    ("SELECT SequenceNumber FROM dbo.Contracts WHERE :contract_id = :contract_id", "current contract"),
    ("SELECT SequenceNumber FROM dbo.Contracts "
     "WHERE EXISTS (SELECT 1 FROM dbo.Contracts c WHERE c.Id = :contract_id)", "current contract"),
    ("SELECT SequenceNumber FROM dbo.Contracts WHERE Id = :contract_id "
     "UNION SELECT SequenceNumber FROM dbo.Contracts", "current contract"),
    ("SELECT FirstName FROM dbo.Customers WHERE Id = :contract_id", "current contract"),
    ("SELECT cu.FirstName FROM dbo.Contracts c, dbo.Customers cu WHERE c.Id = :contract_id", "not joined"),
    ("SELECT cu.FirstName FROM dbo.Contracts c JOIN dbo.Customers cu ON cu.Id = c.Id "
     "WHERE c.Id = :contract_id", "not joined"),
    ("SELECT c.SequenceNumber FROM dbo.Contracts c WHERE NOT (c.Id = :contract_id)", "current contract"),
    ("SELECT r.Amount FROM dbo.Receivables r WHERE r.EntityId = :contract_id", "EntityType = 'CT'"),
    ("WITH x AS (SELECT cu.Email FROM dbo.Customers cu) SELECT x.Email FROM x", "current contract"),
])
def test_unsafe_queries_rejected(sql, fragment):
    errors = validate_sql(sql)
    assert errors, f"expected rejection for: {sql}"
    assert any(fragment.lower() in e.lower() for e in errors), errors


@pytest.mark.parametrize("sql", [
    # customer reached through the finance record, both UNION branches scoped
    "SELECT cu.Email FROM dbo.Customers cu JOIN dbo.LeaseFinances lf ON lf.CustomerId = cu.Id "
    "WHERE lf.ContractId = :contract_id UNION SELECT cu.Email FROM dbo.Customers cu "
    "JOIN dbo.LoanFinances ln ON ln.CustomerId = cu.Id WHERE ln.ContractId = :contract_id",
    # scoped CTE, then an outer query that reads only the CTE
    "WITH p AS (SELECT r.DueDate, rd.Balance FROM dbo.Receivables r "
    "JOIN dbo.ReceivableDetails rd ON rd.ReceivableId = r.Id "
    "WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id) SELECT MAX(p.DueDate) AS LastDue FROM p",
    # contract anchored through Contracts, finance joined by its key
    "SELECT lf.DownPayment FROM dbo.Contracts c JOIN dbo.LeaseFinances lf ON lf.ContractId = c.Id "
    "WHERE c.Id = :contract_id",
])
def test_properly_scoped_queries_pass(sql):
    assert validate_sql(sql) == []


def test_count_star_allowed():
    assert validate_sql("SELECT COUNT(*) AS n FROM dbo.Receivables r "
                        "WHERE r.EntityType = 'CT' AND r.EntityId = :contract_id") == []


def test_restricted_columns_come_from_policy():
    from agent.validator import BLOCKED_COLUMNS
    assert BLOCKED_COLUMNS == {"ssn"}


def test_used_params():
    assert used_params(CORE_TEMPLATES["outstanding_amount"]) == {"contract_id", "as_of_date"}
    assert used_params(CORE_TEMPLATES["status"]) == {"contract_id"}
