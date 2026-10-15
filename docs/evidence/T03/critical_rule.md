# T03 critical rule: PASS (2026-10-15, dev)

Landing `payments_critical.json` (one row with a null `payment_id`) failed the pipeline update:

```
[EXPECTATION_VIOLATION.VERBOSITY_ALL] Flow 'payments_validated' failed to meet the expectation.
Violated expectations: 'payment_id_not_null'. Input data: {... "payment_id": null, ...,
"_source_file": "/Volumes/meridian_dev/<dev schema>/raw/payments/payments_critical.json"}
```

The error names the rule, the offending record and its source file. Recovery: remove the file, then run a
full refresh, which rebuilds the payments tables from the remaining landed files.
