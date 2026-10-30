"""Repeatable smoke replay without replacing any saved research evidence."""
import json
import tempfile

from budgeted_decision.audit import run, verify


def main():
    with tempfile.TemporaryDirectory(prefix="query-budget-smoke-") as output:
        run(output, smoke=True)
        print(json.dumps(verify(output), sort_keys=True))


if __name__ == "__main__":main()
