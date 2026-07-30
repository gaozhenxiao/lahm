import importlib
from typing import Dict, Tuple

from lahm.utils.logging_init import get_logger

logger = get_logger("default")

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "FinancialSituationMemory": ("lahm.agents.utils.memory", "FinancialSituationMemory"),
    "Toolkit": ("lahm.agents.utils.agent_utils", "Toolkit"),
    "create_msg_delete": ("lahm.agents.utils.agent_utils", "create_msg_delete"),
    "AgentState": ("lahm.agents.utils.agent_states", "AgentState"),
    "InvestDebateState": ("lahm.agents.utils.agent_states", "InvestDebateState"),
    "RiskDebateState": ("lahm.agents.utils.agent_states", "RiskDebateState"),
    "create_bear_researcher": ("lahm.agents.researchers.bear_researcher", "create_bear_researcher"),
    "create_bull_researcher": ("lahm.agents.researchers.bull_researcher", "create_bull_researcher"),
    "create_research_manager": ("lahm.agents.managers.research_manager", "create_research_manager"),
    "create_fundamentals_analyst": ("lahm.agents.analysts.fundamentals_analyst", "create_fundamentals_analyst"),
    "create_market_analyst": ("lahm.agents.analysts.market_analyst", "create_market_analyst"),
    "create_news_analyst": ("lahm.agents.analysts.news_analyst", "create_news_analyst"),
    "create_social_media_analyst": ("lahm.agents.analysts.social_media_analyst", "create_social_media_analyst"),
    "create_risky_debator": ("lahm.agents.risk_mgmt.aggresive_debator", "create_risky_debator"),
    "create_safe_debator": ("lahm.agents.risk_mgmt.conservative_debator", "create_safe_debator"),
    "create_neutral_debator": ("lahm.agents.risk_mgmt.neutral_debator", "create_neutral_debator"),
    "create_risk_manager": ("lahm.agents.managers.risk_manager", "create_risk_manager"),
    "create_trader": ("lahm.agents.trader.trader", "create_trader"),
}

__all__ = [
    "FinancialSituationMemory",
    "Toolkit",
    "AgentState",
    "create_msg_delete",
    "InvestDebateState",
    "RiskDebateState",
    "create_bear_researcher",
    "create_bull_researcher",
    "create_research_manager",
    "create_fundamentals_analyst",
    "create_market_analyst",
    "create_neutral_debator",
    "create_news_analyst",
    "create_risky_debator",
    "create_risk_manager",
    "create_safe_debator",
    "create_social_media_analyst",
    "create_trader",
]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)

    module_name, attr_name = _EXPORTS[name]
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals().keys()) | set(_EXPORTS.keys()))
