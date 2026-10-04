"""Single source of truth for the queryable schema: tables, columns and join keys.
Used by the SQL validator (allow-list, contract scoping) and by PII lineage."""

TABLES: dict[str, tuple[str, ...]] = {
    "Contracts": ("Id", "SequenceNumber", "Status", "WorkflowStatus", "CommencementDate", "ContractType"),
    "Customers": ("Id", "FirstName", "LastName", "CustomerType", "AddressLine1", "AddressLine2",
                  "Zip", "SSN", "Phone", "Email"),
    "LeaseFinances": ("Id", "ContractId", "Status", "BookingDate", "DownPayment", "CustomerId"),
    "LoanFinances": ("Id", "ContractId", "Status", "BookingDate", "CustomerId"),
    "PayableInvoices": ("Id", "InvoiceAmount", "Status", "InvoiceDate", "InvoiceTaxAmount", "Currency"),
    "LeaseFundings": ("LeaseFinanceId", "PayableInvoiceId"),
    "Receivables": ("Id", "EntityId", "EntityType", "Amount", "TaxAmount", "DueDate", "IsActive"),
    "ReceivableDetails": ("Id", "ReceivableId", "IsTaxAssessed", "BillingStatus", "DueDate",
                          "Amount", "TaxAmount", "Balance"),
}

TABLE_NAMES = {name.lower() for name in TABLES}
COLUMNS = {table.lower(): {c.lower() for c in cols} for table, cols in TABLES.items()}

# (table, column) pairs that pin a row to one contract when compared with :contract_id.
# Receivables.EntityId only counts together with EntityType = 'CT'.
CONTRACT_KEYS = {
    ("contracts", "id"),
    ("leasefinances", "contractid"),
    ("loanfinances", "contractid"),
    ("receivables", "entityid"),
}

# Join conditions that follow real relationships; a contract-scoped query may only reach
# other tables through these.
FOREIGN_KEYS = {
    frozenset({("leasefinances", "contractid"), ("contracts", "id")}),
    frozenset({("loanfinances", "contractid"), ("contracts", "id")}),
    frozenset({("leasefinances", "customerid"), ("customers", "id")}),
    frozenset({("loanfinances", "customerid"), ("customers", "id")}),
    frozenset({("leasefundings", "leasefinanceid"), ("leasefinances", "id")}),
    frozenset({("leasefundings", "payableinvoiceid"), ("payableinvoices", "id")}),
    frozenset({("receivabledetails", "receivableid"), ("receivables", "id")}),
    frozenset({("receivables", "entityid"), ("contracts", "id")}),
}


def lineage_schema() -> dict:
    """Schema in the shape sqlglot's lineage/optimizer expects."""
    return {"dbo": {table: {col: "VARCHAR" for col in cols} for table, cols in TABLES.items()}}
