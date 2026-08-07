# Python Typing

## Principles

- Follow the repository's supported Python versions and type-checker settings.
- Type public boundaries and non-obvious internal contracts where annotations
  improve correctness and maintenance.
- Prefer precise domain types, protocols, generics, and abstract collection
  types over unnecessarily concrete parameters.
- Use `Any` deliberately at genuinely dynamic or untyped boundaries; narrow or
  validate it before relying on its structure.
- Match the existing annotation style instead of rewriting equivalent syntax.
- Avoid mutable default arguments. Use an immutable default, sentinel, or
  default factory appropriate to the API.
- Use keyword-only parameters when positional ordering would be ambiguous or
  error-prone, while preserving existing public-call compatibility.

## Runtime Boundaries

- Remember that annotations may be evaluated at runtime by frameworks,
  serializers, decorators, and reflection tools.
- Use `TYPE_CHECKING` only for imports not needed by runtime behavior.
- Prefer `isinstance` for polymorphic runtime checks when subclasses are valid.
- Handle unsupported variants explicitly rather than allowing obscure attribute
  failures.
- Do not use `assert` for validation of untrusted input or required production
  invariants because optimized execution may remove it. Assertions remain useful
  for internal states that are truly impossible if the program is correct.

## Compatibility

- Treat exported annotations as part of the developer-facing contract when
  callers or tools depend on them.
- Do not modernize syntax beyond the project's minimum Python version.
- Validate type-checker changes with the repository's configured command, not a
  locally preferred checker or stricter unapproved settings.
