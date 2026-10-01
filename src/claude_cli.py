"""synthetic stub: LLM CLI wrapper interface used by channel_analysis/analyze.py.

The real implementation (subprocess call to a local LLM CLI) is not included.
Implement run_claude_cli() for your environment; the signature below is what
analyze.py expects.
"""
import json
import re


def run_claude_cli(system: str, prompt: str, *, model: str = "haiku", tools=None, timeout: int = 240) -> str:
    raise NotImplementedError("synthetic stub: plug in your LLM call here")


def parse_json_loose(raw: str):
    """Parse JSON, tolerating code fences / leading prose."""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if not m:
            raise ValueError("no JSON object found")
        return json.loads(m.group(0))
