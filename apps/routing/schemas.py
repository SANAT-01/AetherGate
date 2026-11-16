from pydantic import BaseModel, Field


class RoutingChainAttempt(BaseModel):
    provider: str
    model: str
    timeout: float = 30.0


class RoutingRules(BaseModel):
    # Primary + up to 2 fallbacks. Unbounded chains risk stacking timeouts
    # across many attempts, undermining the hot-path latency goal.
    chain: list[RoutingChainAttempt] = Field(min_length=1, max_length=3)
