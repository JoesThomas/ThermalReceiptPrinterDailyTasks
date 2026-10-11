# Repayment records on finance receipts

The regular and test finance receipts use the same canonical repayment records.
Names are compared without case, spaces or punctuation, and an existing
`monthly_commitment_name` explicitly links different labels. Instalment records
take precedence over matching debt records.

A generic `Amazon Monthly Payments` label (optionally followed by a date) is
removed when there is exactly one named payment plan with the same positive
monthly payment and outstanding balance. Matching the payment amount alone is
insufficient; ambiguous records remain visible. This avoids counting a product
plan twice in amounts owed, monthly repayments and test repayment options.
Separate plans with different amounts or balances remain separate.

This is record deduplication, not payment verification. Missing bank data does
not mark a repayment as paid, and real Amazon purchase transactions remain in
spending totals. Existing private source files are unchanged.
