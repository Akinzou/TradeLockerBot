"""An outcome returned as a value: ``Ok`` with the answer or ``Err`` with why
there is none (ADR 0006).

Two plain classes and a union rather than a library: the layer rule admits no
third-party package, and callers branch with ``isinstance`` or ``match``,
which type checkers narrow without any helper API.

A result refuses to be tested for truth. ``Ok(0)`` and ``Ok(None)`` would
otherwise be truthy, so code that forgot to unwrap, such as
``while not order_id:``, would stop retrying without any error.
"""

from dataclasses import dataclass
from typing import Generic, NoReturn, TypeVar, Union

T = TypeVar("T")
E = TypeVar("E")


def _refuse_truth_test(result) -> NoReturn:
    raise TypeError(f"unwrap {type(result).__name__} before testing it: use isinstance or match")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T

    __bool__ = _refuse_truth_test


@dataclass(frozen=True)
class Err(Generic[E]):
    error: E

    __bool__ = _refuse_truth_test


Result = Union[Ok[T], Err[E]]
