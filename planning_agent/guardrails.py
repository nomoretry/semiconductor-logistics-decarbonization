"""Numeric faithfulness check for agent answers.

Every number in a final answer must be traceable to a tool result or to the
user's own message, allowing for the rounding a writer would naturally apply.
The allowed rounding follows the precision the answer itself shows: "12.4%"
may round 12.38, "6.8千" or "6,800" may round 6,842, but "9,999" must match
to the unit. Numbers the model computed or invented are reported so the agent
can be asked to rewrite, and are flagged in the final answer if it does not.
"""
from __future__ import annotations

import json
import re

# A number may follow Chinese text directly ("增加4,537美元"), so only ASCII word characters, dots and
# commas block a match: they keep "P3" out and stop a match from starting inside "4,537" or "1.5".
NUMBER = re.compile(r"(?<![A-Za-z0-9_.,])([-+−]?\d[\d,]*(?:\.\d+)?)\s*(万|千|[kK](?![a-zA-Z])|%)?")
SCALE = {"万": 1e4, "千": 1e3, "k": 1e3, "K": 1e3}


def numbers_in(text: str) -> list[tuple[str, float, float]]:
    """(raw text, value, precision of the last shown digit) for every number in text."""
    found = []
    for match in NUMBER.finditer(text):
        raw, unit = match.group(1).replace("−", "-"), match.group(2) or ""
        digits = raw.replace(",", "").lstrip("+-")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if "." in digits:
            precision = 10.0 ** -len(digits.split(".")[1])
        elif value >= 1000:
            precision = 10.0 ** (len(digits) - len(digits.rstrip("0")))  # 6,800 may be a rounded 6,842
        else:
            precision = 1.0
        scale = SCALE.get(unit, 1.0)
        found.append((match.group(0).strip(), value * scale, precision * scale))
    return found


def grounded_values(sources) -> list[float]:
    values = set()
    for source in sources:
        text = source if isinstance(source, str) else json.dumps(source, ensure_ascii=False, default=str)
        for _, value, _ in numbers_in(text):
            values.update({abs(value), abs(value) * 100, abs(value) / 100})
    return sorted(values)


def supported(value: float, precision: float, grounded: list[float]) -> bool:
    """True if some grounded value rounds to the answer's number at the precision the answer shows."""
    target = abs(value)
    return any(abs(target - g) <= precision / 2 + 1e-6 * max(1.0, g) for g in grounded)


def check_answer(answer: str, tool_results, user_text: str = "") -> dict:
    grounded = grounded_values([*tool_results, user_text])
    numbers = numbers_in(answer)
    unsupported = [raw for raw, value, precision in numbers if not supported(value, precision, grounded)]
    return {"ok": not unsupported, "unsupported": unsupported, "checked": len(numbers)}
