"""
analyzer.py
-----------
AI analysis layer. Owns all API calls.

Fallback order: Claude Sonnet 4 → Groq Llama 3.3 70B → Exception

Both providers return the same JSON schema.
Never hardcodes analysis rules — always loaded from SKILL.md.
"""

import json
import os
import anthropic
from pathlib import Path

SKILL_PATH  = Path(__file__).parent / "skills" / "nse-setup-analysis" / "SKILL.md"
CLAUDE_MODEL = "claude-sonnet-4-6"
GROQ_MODEL   = "llama-3.3-70b-versatile"

JSON_INSTRUCTION = """

OUTPUT FORMAT: Return ONLY valid JSON. No markdown fences, no preamble, no explanation.
Schema:
{
  "ticker": "string",
  "timeframes": {
    "monthly": {"trend": "string", "levels": ["string"], "view": "bullish|bearish|neutral|unclear|not_described"},
    "weekly":  {"trend": "string", "levels": ["string"], "view": "bullish|bearish|neutral|unclear|not_described"},
    "daily":   {"trend": "string", "levels": ["string"], "view": "bullish|bearish|neutral|unclear|not_described"},
    "h1":      {"trend": "string", "levels": ["string"], "view": "bullish|bearish|neutral|unclear|not_described"}
  },
  "bullish_count": 0,
  "alignment_summary": "string",
  "risk": {
    "entry": null, "sl": null, "target": null,
    "risk_pct": null, "rr": null, "risk_pass": null
  },
  "governance": {
    "nse_cash":     "pass|fail|unknown",
    "swing_period": "pass|fail|unknown",
    "not_intraday": "pass|fail|unknown",
    "risk_limit":   "pass|fail|not_calculable",
    "no_auto":      "pass"
  },
  "governance_overall": "clear|needs_review|blocked",
  "narrative": "2-4 sentence plain summary",
  "missing_info": ["string"]
}
"""


def _load_skill() -> str:
    """Load SKILL.md content. Raises if file not found."""
    return SKILL_PATH.read_text(encoding="utf-8")


def _build_user_msg(ticker, monthly, weekly, daily, h1, entry, sl, target) -> str:
    msg = (
        f"Analyze {ticker.upper().strip()}:\n"
        f"Monthly: {monthly or 'not described'}\n"
        f"Weekly:  {weekly  or 'not described'}\n"
        f"Daily:   {daily   or 'not described'}\n"
        f"1H:      {h1      or 'not described'}\n"
    )
    if entry:  msg += f"Entry:     ₹{entry}\n"
    if sl:     msg += f"Stop-loss: ₹{sl}\n"
    if target: msg += f"Target:    ₹{target}\n"
    return msg


def _parse_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


# ── Provider: Claude ───────────────────────────────────────────────────────────

def _call_claude(skill_text: str, user_msg: str) -> dict:
    """Call Claude Sonnet 4 with prompt caching."""
    client = anthropic.Anthropic()

    system = [
        {
            "type": "text",
            "text": skill_text + JSON_INSTRUCTION,
            "cache_control": {"type": "ephemeral"},  # ~90% cost saving on repeated calls
        }
    ]

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    # Log token usage
    u = response.usage
    print(
        f"[Claude] input={u.input_tokens} | "
        f"cache_read={getattr(u,'cache_read_input_tokens',0)} | "
        f"cache_write={getattr(u,'cache_creation_input_tokens',0)} | "
        f"output={u.output_tokens}"
    )

    return _parse_json(response.content[0].text)


# ── Provider: Groq ─────────────────────────────────────────────────────────────

def _call_groq(skill_text: str, user_msg: str) -> dict:
    """Call Groq Llama 3.3 70B as fallback. OpenAI-compatible API."""
    try:
        import groq as groq_sdk
    except ImportError:
        raise ImportError("groq package not installed. Run: pip install groq")

    client = groq_sdk.Groq(api_key=os.environ["GROQ_API_KEY"])

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": skill_text + JSON_INSTRUCTION},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.1,  # low = consistent JSON structure
        max_tokens=1000,
    )

    raw = response.choices[0].message.content
    print(
        f"[Groq]   model={GROQ_MODEL} | "
        f"input={response.usage.prompt_tokens} | "
        f"output={response.usage.completion_tokens}"
    )

    return _parse_json(raw)


# ── Public API ─────────────────────────────────────────────────────────────────

def analyze_setup(
    ticker:  str,
    monthly: str = "",
    weekly:  str = "",
    daily:   str = "",
    h1:      str = "",
    entry:   str = "",
    sl:      str = "",
    target:  str = "",
) -> tuple[dict, str]:
    """
    Run multi-timeframe setup analysis.

    Returns (analysis_dict, provider_used) where provider_used is
    "claude" or "groq".

    Raises Exception only if BOTH providers fail.
    """
    skill_text = _load_skill()
    user_msg   = _build_user_msg(ticker, monthly, weekly, daily, h1, entry, sl, target)
    errors     = {}

    # 1. Try Claude
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            result = _call_claude(skill_text, user_msg)
            return result, "claude"
        except Exception as e:
            errors["claude"] = str(e)
            print(f"[Claude] failed — {e}. Trying Groq...")
    else:
        errors["claude"] = "ANTHROPIC_API_KEY not set"
        print("[Claude] ANTHROPIC_API_KEY not set — skipping to Groq.")

    # 2. Try Groq
    if os.environ.get("GROQ_API_KEY"):
        try:
            result = _call_groq(skill_text, user_msg)
            return result, "groq"
        except Exception as e:
            errors["groq"] = str(e)
            print(f"[Groq] failed — {e}.")
    else:
        errors["groq"] = "GROQ_API_KEY not set"

    # Both failed
    raise Exception(
        f"All providers failed.\n"
        f"  Claude: {errors.get('claude','not attempted')}\n"
        f"  Groq:   {errors.get('groq','not attempted')}"
    )
