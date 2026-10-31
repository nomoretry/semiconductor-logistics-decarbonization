"""Supply-chain planning copilot: an LLM tool-calling agent over the network planning engine.

Without LLM_API_KEY the deterministic rule agent answers instead, so every
command runs offline. The tools need the optional ``planning`` extra; the
guardrail and LLM client modules import without it.

Entry points: ``planning_agent.agent.run_llm``, ``planning_agent.rules.run_rules``
and ``planning_agent.tools.Session``.
"""
