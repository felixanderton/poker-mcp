---
paths:
  - "**/*"
---

# General Coding Standards

## Change discipline

- Make the minimum change needed. Do not refactor, rename, or reorganise code outside the scope of the task.
- Do not add comments, docstrings, or type annotations to code you did not write or change.
- Do not add error handling for scenarios that cannot happen in practice.
- Never create helpers, utilities, or abstractions for a one-time use — three similar lines is better than a premature abstraction.

## Consistency

- Read the surrounding code before writing anything. Match its style, naming, and patterns exactly.
- Follow the existing directory and file naming conventions of the project.
- If something similar already exists, extend it rather than creating a parallel version.

## Security

- Never hardcode secrets, API keys, tokens, or credentials — use environment variables or config files.
- Validate all user-supplied input at system boundaries (user input, external APIs).
- Never construct shell commands from user-controlled data.

## Collaboration

- If a requirement seems architecturally risky, inconsistent, or there is a clearly better approach, say so before implementing — explain the tradeoff and ask how to proceed.
- Ask clarifying questions rather than making assumptions on ambiguous requirements.
- Raise concerns early, before writing code, not after.
- Do not silently comply with something that looks wrong. A short challenge is more valuable than correct execution of a bad idea.

## Agent usage

- Run the `reviewer` agent before committing any non-trivial change.
- Use the `feature-writer` agent for implementing features from a spec.
- Use the `test-writer` agent to add coverage after a feature is built.
