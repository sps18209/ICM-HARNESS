# Integration Adapters

Each integration is a separate Python package. Core modules do not import these packages.

An adapter may be replaced or upgraded if it continues to satisfy the corresponding core contract.
Do not place mode semantics, routing weights, Context Wiki rules, or Planner/Writer/Tester policy here.
