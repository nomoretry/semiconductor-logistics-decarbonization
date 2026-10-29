# Research repository working rules

Use Python for experiments and Markdown for documentation. Do not replace research code with an HTML presentation.

For each substantive research change:

1. Record the question, source evidence and assumptions before interpreting results.
2. Save runnable code/configuration, raw per-case evidence, comparison baselines and a replay command.
3. Update `docs/research_log.md` and the five-stage ledger in `docs/progress.md` in the same pull request. Link exact source and artifact paths. Preserve failed gates and negative results.
4. Label development, synthetic, exploratory, assistant-reviewed and human-reviewed evidence accurately. Count distinct cases separately from repeated calls, goals and seeds.
5. Keep prior frozen API runners, prompts, data and archived ledgers unchanged. Extend with a separate version/package when the task contract changes.
6. Run appropriate offline tests and artifact verification. Live API runs remain separate manual workflows with a bounded budget and repository Secret; do not add credentials to files.
7. Train BC/PPO only after strong adaptive and optimization baselines leave a measurable quality or computation tradeoff. Task count alone does not satisfy this condition.

Documentation should state the problem, implementation, measured result and next acceptance condition. Avoid date headings, promotional claims and claims of enterprise deployment or broad LLM generalization.
