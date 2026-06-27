import time
import os
from typing import Any, Dict

from langchain_core.callbacks.base import BaseCallbackHandler
from prometheus_client import Counter, Histogram


AI_REQUESTS_TOTAL = Counter(
    "ai_requests_total",
    "Total number of AI model requests",
    labelnames=("model", "status"),
)

AI_ERRORS_TOTAL = Counter(
    "ai_errors_total",
    "Total number of AI model errors",
    labelnames=("model", "error_type"),
)

AI_TOKENS_TOTAL = Counter(
    "ai_tokens_total",
    "Total token usage by AI model",
    labelnames=("model", "token_type"),
)

AI_REQUEST_DURATION_SECONDS = Histogram(
    "ai_request_duration_seconds",
    "AI model request duration in seconds",
    labelnames=("model", "status"),
    buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34),
)

AI_TOKENS_PER_REQUEST = Histogram(
    "ai_tokens_per_request",
    "Total AI tokens used per request",
    labelnames=("model", "status"),
    buckets=(50, 100, 200, 400, 800, 1200, 2000, 3200, 5000, 8000, 13000),
)

AI_COST_USD_TOTAL = Counter(
    "ai_cost_usd_total",
    "Estimated AI model cost in USD",
    labelnames=("model",),
)

AI_PARSE_FAILURES_TOTAL = Counter(
    "ai_parse_failures_total",
    "Total AI response parsing/validation failures",
    labelnames=("model", "reason"),
)


def _coerce_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (ValueError, TypeError):
        return 0


def _extract_token_usage(raw_response: Any) -> Dict[str, int]:
    """Extract token usage from common LangChain/OpenAI response layouts."""
    if raw_response is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _normalize_usage(data: Dict[str, Any]) -> Dict[str, int]:
        prompt_tokens = _coerce_int(
            data.get("prompt_tokens", data.get("input_tokens", data.get("promptTokenCount")))
        )
        completion_tokens = _coerce_int(
            data.get("completion_tokens", data.get("output_tokens", data.get("candidatesTokenCount")))
        )
        total_tokens = _coerce_int(
            data.get("total_tokens", data.get("totalTokenCount"))
        )

        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    llm_output = getattr(raw_response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}

    if not token_usage:
        generations = getattr(raw_response, "generations", None) or []
        if generations and generations[0]:
            first_gen = generations[0][0]
            message = getattr(first_gen, "message", None)

            usage_metadata = getattr(message, "usage_metadata", None) if message else None
            if isinstance(usage_metadata, dict) and usage_metadata:
                token_usage = usage_metadata

            response_metadata = getattr(message, "response_metadata", None) if message else None
            if isinstance(response_metadata, dict):
                token_usage = (
                    token_usage
                    or response_metadata.get("token_usage")
                    or response_metadata.get("usage")
                    or response_metadata.get("usage_metadata")
                    or {}
                )

            generation_info = getattr(first_gen, "generation_info", None) or {}
            if isinstance(generation_info, dict):
                token_usage = (
                    token_usage
                    or generation_info.get("token_usage")
                    or generation_info.get("usage")
                    or {}
                )

    return _normalize_usage(token_usage if isinstance(token_usage, dict) else {})


def observe_ai_request(model: str, status: str, duration_seconds: float) -> None:
    AI_REQUESTS_TOTAL.labels(model=model, status=status).inc()
    AI_REQUEST_DURATION_SECONDS.labels(model=model, status=status).observe(duration_seconds)


def observe_ai_error(model: str, error_type: str) -> None:
    AI_ERRORS_TOTAL.labels(model=model, error_type=error_type).inc()


def observe_token_usage(model: str, usage: Dict[str, int]) -> None:
    AI_TOKENS_TOTAL.labels(model=model, token_type="prompt").inc(usage.get("prompt_tokens", 0))
    AI_TOKENS_TOTAL.labels(model=model, token_type="completion").inc(usage.get("completion_tokens", 0))
    AI_TOKENS_TOTAL.labels(model=model, token_type="total").inc(usage.get("total_tokens", 0))


def observe_tokens_per_request(model: str, status: str, usage: Dict[str, int]) -> None:
    AI_TOKENS_PER_REQUEST.labels(model=model, status=status).observe(usage.get("total_tokens", 0))


def observe_ai_cost(model: str, usage: Dict[str, int]) -> float:
    estimated_cost = estimate_cost_usd(model=model, usage=usage)
    if estimated_cost > 0:
        AI_COST_USD_TOTAL.labels(model=model).inc(estimated_cost)
    return estimated_cost


def observe_parse_failure(model: str, reason: str) -> None:
    AI_PARSE_FAILURES_TOTAL.labels(model=model, reason=reason).inc()


def validate_invoice_response(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "not_object"

    required_sections = ("invoice_details", "vendor", "items", "invoice_summary")
    for section in required_sections:
        if section not in payload:
            return False, f"missing_{section}"

    if not isinstance(payload.get("items"), list):
        return False, "items_not_list"

    return True, "ok"


def _price_per_million_tokens(model: str) -> tuple[float, float]:
    default_input = float(os.getenv("AI_PRICE_GPT4O_INPUT_PER_1M", "5"))
    default_output = float(os.getenv("AI_PRICE_GPT4O_OUTPUT_PER_1M", "15"))

    table = {
        "gpt-4o": (
            float(os.getenv("AI_PRICE_GPT4O_INPUT_PER_1M", str(default_input))),
            float(os.getenv("AI_PRICE_GPT4O_OUTPUT_PER_1M", str(default_output))),
        )
    }
    return table.get(model, (default_input, default_output))


def estimate_cost_usd(model: str, usage: Dict[str, int]) -> float:
    input_per_1m, output_per_1m = _price_per_million_tokens(model)
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)

    estimated = (prompt / 1_000_000.0) * input_per_1m + (completion / 1_000_000.0) * output_per_1m
    return max(estimated, 0.0)


class AIUsageCallbackHandler(BaseCallbackHandler):
    """Capture token usage from LangChain callbacks and expose latest usage."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.last_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _extract_token_usage(response)
        self.last_usage = usage
        observe_token_usage(self.model_name, usage)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        # Errors are tracked in the request-level exception path.
        return
