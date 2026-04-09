# Client Coding Standards

## TypeScript

- No `any`. Use `unknown` when the type is genuinely unknown.
- Prefer narrowly inferred types; avoid explicit annotations where inference is accurate.
- Type assertions (`as`) must be rare and justified.

## Functions

- ≤ 5 meaningful actions per function, typically ~5 lines.
- Single level of abstraction per function — if a function orchestrates, it calls named helpers; it does not contain inline implementation details.

## Arguments

- 1–2 arguments preferred; 3 is borderline; 4+ is a violation.

## Naming

- Names must convey intent precisely. Avoid vague names (`data`, `item`, `temp`, `handle`, `process`).
- Boolean variables/functions must read as predicates: `isLoading`, `hasError`, `canSubmit`.
- Event handlers must describe what happened, not the implementation: `onUserSelected` not `handleClick`.

## Mutability

- `const` everywhere. `let` requires justification. `var` is prohibited.

## Functional Programming

- Prefer pure functions, immutability, and function composition over imperative mutation.
- Prefer declarative array methods (`filter`, `map`, `flatMap`, `reduce`) over imperative `for`/`forEach` loops.

## Comments

Whenever making a code change that is not immediately obvious — e.g. a workaround, a non-obvious flag, a subtle timing dependency, or a browser-specific fix — add a concise inline comment explaining why it is needed. One to three lines is usually enough. Skip comments where the code is self-evident.

## CSS / Styling

- Never concatenate classNames with array `.join(" ")`. Use template literals or a classnames utility.

## File Naming

- Non-component files (hooks, utilities): **camelCase** (e.g., `useSSE.ts`)
- Component files: **PascalCase** matching the component name (e.g., `SessionCard.tsx`)
