---
paths:
  - "**/*.py"
---

# Python Standards

## Type hints

All code must be fully typed. Mypy must pass clean.

- Type all function arguments, return values, and class attributes — no bare `Any` unless unavoidable
- Use `X | Y` union syntax — never `Optional[X]` or `Union[X, Y]`
- Use built-in generic types: `list[T]`, `dict[K, V]`, `tuple[T, ...]` — never `List`, `Dict`, `Tuple` from `typing`
- Use the `type` keyword for type aliases: `type Scores = dict[str, float]`
- Use `@override` from `typing` when overriding a parent method

```python
# Correct
def process(items: list[str], limit: int | None = None) -> dict[str, int]:
    ...

type Matrix = list[list[float]]

# Wrong
from typing import Optional, List, Dict
def process(items: List[str], limit: Optional[int] = None) -> Dict[str, int]:
    ...
```

If a type truly cannot be known, use a narrow `# type: ignore[<error-code>]` with a comment explaining why — never a blanket ignore.

## Structured data

Use Pydantic `BaseModel` for any structured data: configs, API payloads, data records, model parameters.

- Inherit from `pydantic.BaseModel`
- Use `Field(...)` for validation constraints and metadata
- Load from external sources with `Model.model_validate(data)`, not `Model(**data)`
- Use `model_config = ConfigDict(frozen=True)` for configs that should not be mutated after creation

```python
from pydantic import BaseModel, Field, ConfigDict

class TrainingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    learning_rate: float = Field(default=0.001, gt=0, description="Adam LR")
    batch_size: int = Field(default=32, ge=1)
    epochs: int = 10
```

Use plain dataclasses only for simple internal data structures that need no validation. Use plain dicts only for genuinely ad-hoc, unstructured data.

## Tooling

After editing any Python file, run:

```bash
ruff check --fix . && black . && mypy .
```

Or scoped to the changed file:

```bash
ruff check --fix <file> && black <file> && mypy <file>
```

Do not leave the session with mypy errors unresolved.

## Style

- **f-strings only**: `f"Hello {name}"` — never `%` formatting or `.format()`
- **pathlib over os.path**: use `Path` for all file and directory operations
- **match/case**: use for multi-branch dispatch on a single value instead of long `if/elif` chains
- **logging over print**: use the `logging` module for diagnostic output in any non-script code
- **no mutable defaults**: never `def fn(items=[])` — use `= None` with a guard or `Field(default_factory=list)`
- **short functions**: if a function requires more than two levels of nesting, split it
