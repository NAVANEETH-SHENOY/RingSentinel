"""Runtime guard for the held-out test split (data stage D7: "test is never used in fitting").

Fitting code receives `fit_view()`, which has no test entry at all. The test data can be
released only through `release_test(detector)`, and only once per detector, so a detector's
test score is computed exactly once. Test data are supplied as loaders and are not touched
until released, which lets a test poison the loader and prove that fitting never reads it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class TestSplitAccessError(RuntimeError):
    """Raised when test data is requested in a way the protocol does not allow."""

    __test__ = False  # not a pytest test class


class SplitVault:
    def __init__(self, fit_splits: Mapping[str, Any], test_loader: Callable[[], Any]) -> None:
        if "test" in fit_splits:
            raise TestSplitAccessError("fit splits must not contain the test split.")
        self._fit = dict(fit_splits)
        self._test_loader = test_loader
        self._released: set[str] = set()

    def fit_view(self) -> dict[str, Any]:
        """Train and validation only."""
        return dict(self._fit)

    def release_test(self, detector: str) -> Any:
        """Hand out the test data for one detector, once."""
        if detector in self._released:
            raise TestSplitAccessError(
                f"The test split was already scored for {detector!r}. It is scored once."
            )
        self._released.add(detector)
        return self._test_loader()

    @property
    def released(self) -> frozenset[str]:
        return frozenset(self._released)
