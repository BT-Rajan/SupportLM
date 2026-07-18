"""Hardcoded per-provider/model pricing for estimated cost tracking
(Phase 7 — 0.2).

**These figures WILL go stale and are not independently verified
against each provider's current, live pricing page as of the date this
is actually deployed.** Provider prices change over time; this table
reflects this session's best available knowledge at the time it was
written, not a live-fetched or contractually-guaranteed rate. Treat
`estimated_cost_usd` on every `llm_usage_log` row as a directional
estimate for relative cost tracking across tenants/providers, not an
exact billing reconciliation figure — verify and update the numbers
below periodically against each provider's actual pricing page.
"""
import logging
from decimal import Decimal

logger = logging.getLogger("supportlm.llm_pricing")

# All figures are USD per 1,000 tokens.
PRICING: dict[str, dict[str, dict[str, Decimal]]] = {
    "deepseek": {
        "deepseek-chat": {"input_per_1k": Decimal("0.00014"), "output_per_1k": Decimal("0.00028")},
    },
    "openai": {
        "gpt-4o-mini": {"input_per_1k": Decimal("0.00015"), "output_per_1k": Decimal("0.00060")},
    },
    "anthropic": {
        "claude-3-5-sonnet-20241022": {"input_per_1k": Decimal("0.003"), "output_per_1k": Decimal("0.015")},
    },
}


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Falls back to $0 with a logged warning for any provider/model
    combination not in the table above — a tenant on an unrecognized
    or brand-new model shouldn't crash cost tracking, just visibly
    under-report it in the logs rather than raising."""
    rates = PRICING.get(provider, {}).get(model)
    if rates is None:
        logger.warning(
            "No pricing entry for provider=%s model=%s — cost will be recorded as $0 for this request. "
            "Add an entry to app/core/llm_pricing.py's PRICING table.",
            provider,
            model,
        )
        return Decimal("0")

    input_cost = (Decimal(input_tokens) / Decimal(1000)) * rates["input_per_1k"]
    output_cost = (Decimal(output_tokens) / Decimal(1000)) * rates["output_per_1k"]
    return input_cost + output_cost
