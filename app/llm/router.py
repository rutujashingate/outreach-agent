"""Optional task routing, enabled only with recorded evaluation measurements."""

from pydantic import BaseModel, Field

from app.llm.client import ModelClient


class TaskMeasurement(BaseModel):
    quality: float = Field(ge=0, le=1, allow_inf_nan=False)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)
    source: str = Field(min_length=1)


class ModelRouter:
    """Use measured routes where supplied, otherwise use the existing client."""

    def __init__(self, default: ModelClient, routes: dict[str, ModelClient] | None = None,
                 measurements: dict[str, TaskMeasurement] | None = None,
                 minimum_quality: float = 0.8):
        self.default, self.routes = default, routes or {}
        self.last_usage = {}
        self.model_name = None
        measurements = measurements or {}
        for task in self.routes:
            if task not in measurements or measurements[task].quality < minimum_quality:
                raise ValueError(f"Model route for {task} requires adequate recorded measurements.")

    async def generate_structured(self, *, instructions, input_text, response_model):
        # Record class names identify the tasks without changing the shared API.
        client = self.routes.get(response_model.__name__, self.default)
        result = await client.generate_structured(instructions=instructions, input_text=input_text,
                                                   response_model=response_model)
        self.last_usage = getattr(client, "last_usage", {})
        self.model_name = getattr(client, "model_name", None)
        return result
