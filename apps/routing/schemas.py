from pydantic import BaseModel, Field


class RoutingChainAttempt(BaseModel):
    provider: str
    # None means "use whatever model the client requested in the payload"
    # instead of pinning this chain entry to a fixed model.
    model: str | None = None
    timeout: float = 30.0


class RoutingRules(BaseModel):
    # Primary + up to 2 fallbacks. Unbounded chains risk stacking timeouts
    # across many attempts, undermining the hot-path latency goal.
    chain: list[RoutingChainAttempt] = Field(min_length=1, max_length=3)
