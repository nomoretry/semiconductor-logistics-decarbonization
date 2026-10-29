"""Exploratory evaluation of recorded official-notice excerpts.

This package does not alter the frozen synthetic benchmark or call an API.
References are assistant reviewed and remain pending independent human review.
"""

from .data import load_dataset, validate_dataset
from .evaluation import evaluate_offline, score_predictions

__all__ = ["load_dataset", "validate_dataset", "evaluate_offline", "score_predictions"]
