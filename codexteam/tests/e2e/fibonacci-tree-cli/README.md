# Fibonacci Tree CLI E2E Fixture

This fixture drives one controlled CodexTeam canary from project initialization through delivery.

The canary has five sequential, project-specific tasks:

1. a leader validates the initialized specification and handoffs;
2. one developer implements the complete CLI and its tests;
3. a tester records independent acceptance evidence;
4. a reviewer audits the evidence and spot-checks the product;
5. a documenter prepares delivery material.

Every task uses one persistent attempt with a draft turn and a final turn. The runner performs a deterministic gate between those turns, validates the single final result, and closes the task independently. It never retries, changes profile, or transfers ownership automatically.

Contents:

- `template/`: custom project template rendered by the canonical initializer;
- `prompts/`: Project Lead acceptance prompts used for finalization;
- `golden/fib-4.txt`: exact expected output for the product smoke test.

The fixture is intentionally product-specific. It is not an alternate project initializer and is not installed into generated projects outside this canary.
