# Architecture Change Playbook

Use when an approved change affects public contracts, persistence, deployment, security boundaries, concurrency, or cross-component dependency direction.

1. Confirm the architecture trigger and named requirements with the Project Lead.
2. Inspect the existing architecture and only the affected implementation boundaries.
3. Draft the smallest viable architecture delta and repository-map change.
4. Record material alternatives and compatibility or migration consequences.
5. Map Development and Integration Gate coverage to the changed boundaries.
6. Return the proposal for Project Lead approval before implementation starts.
7. After implementation, let the Reviewer audit architecture conformance independently.

Stop if the requirements do not determine a safe boundary or an unapproved dependency is required.
