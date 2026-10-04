"""Golden answers at as-of 2026-10-01 (mirrors db/expected_answers.md)."""
from datetime import date
from decimal import Decimal as D

AS_OF = date(2026, 10, 1)

# seq: (status, workflow, next_due_date, next_due_total, invoice_count, invoice_amount, invoice_tax, outstanding)
GOLDEN = {
    "CT-1001": ("Commenced",   "Commenced",           "2026-11-01", D("1080"), 1, D("45000"),  D("3600"), D("2160")),
    "CT-1002": ("Commenced",   "Commenced",           "2026-11-01", D("2700"), 1, D("120000"), D("9600"), D("0")),
    "CT-1003": ("Commenced",   "Commenced",           "2026-09-15", D("750"),  0, None,        None,      D("1500")),
    "CT-1004": ("PaidOff",     "Commenced",           None,         None,      0, None,        None,      D("0")),
    "CT-1005": ("Restructure", "Commenced",           "2026-11-01", D("972"),  1, D("60000"),  D("4800"), D("1944")),
    "CT-1006": ("Rebook",      "Commenced",           "2026-11-01", D("1944"), 3, D("70000"),  D("5600"), D("1944")),
    "CT-1007": ("Not yet commenced", "Documents Submitted", None,         None,      0, None,        None,      D("0")),
    "CT-1008": ("Commenced",   "Commenced",           "2026-11-01", D("1500"), 0, None,        None,      D("1500")),
    "CT-1009": ("Commenced",   "Commenced",           "2026-11-01", D("1188"), 1, D("52000"),  D("4160"), D("2376")),
    "CT-1010": ("Commenced",   "Commenced",           "2026-11-01", D("2000"), 0, None,        None,      D("4000")),
    "CT-1011": ("Commenced",   "Commenced",           "2026-11-01", D("1620"), 1, D("70000"),  D("5600"), D("3480")),
    "CT-1012": ("Commenced",   "Documents Revision",  None,         None,      0, None,        None,      D("0")),
}


def check_rows(intent: str, rows: list[dict], expected: tuple) -> None:
    """Assert template result rows match the golden tuple for one contract."""
    status, workflow, next_due, next_total, inv_count, inv_amount, inv_tax, outstanding = expected
    if intent == "status":
        assert rows == [{"Status": status, "WorkflowStatus": workflow}]
    elif intent == "next_due_date":
        if next_due is None:
            assert rows == []
        else:
            assert rows[0]["NextDueDate"] == next_due
            assert D(rows[0]["Amount"]) + D(rows[0]["TaxAmount"]) == next_total
    elif intent == "invoice_amount":
        if inv_count == 0:
            assert rows == []
        else:
            assert rows[0]["InvoiceCount"] == inv_count
            assert D(rows[0]["InvoiceAmount"]) == inv_amount
            assert D(rows[0]["InvoiceTaxAmount"]) == inv_tax
    elif intent == "outstanding_amount":
        assert D(rows[0]["OutstandingTotal"]) == outstanding
    else:
        raise ValueError(intent)
