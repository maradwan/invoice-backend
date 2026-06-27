import base64
import logging
import os
import re
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Dict, Any

from opentelemetry import trace
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from core.ai_observability import (
    AIUsageCallbackHandler,
    observe_ai_error,
    observe_ai_cost,
    observe_parse_failure,
    observe_ai_request,
    observe_tokens_per_request,
    validate_invoice_response,
)
from core.langfuse_observability import (
    build_langfuse_metadata,
    create_langfuse_client,
    submit_langfuse_score,
)
from invoice_schema import INVOICE_SCHEMA


logger = logging.getLogger(__name__)


REDACTED_VALUE = "[REDACTED]"
PII_KEYWORDS = {
    "email",
    "phone",
    "mobile",
    "contact",
    "vat",
    "tax",
    "iban",
    "account",
    "address",
    "crn",
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None

        cleaned = cleaned.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    return None


def _trace_version_metadata() -> Dict[str, str]:
    return {
        "prompt_version": os.getenv("INVOICE_PROMPT_VERSION", "v1"),
        "extraction_version": os.getenv("INVOICE_EXTRACTION_VERSION", "v1"),
    }


def _mask_string_pii(value: str) -> tuple[str, bool]:
    redacted = value
    redactions = 0

    # Email addresses
    redacted, changed = re.subn(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        REDACTED_VALUE,
        redacted,
    )
    redactions += changed

    # Phone-like patterns (7+ digits, optional separators/prefix)
    redacted, changed = re.subn(
        r"\+?\d[\d\s\-()]{6,}\d",
        REDACTED_VALUE,
        redacted,
    )
    redactions += changed

    return redacted, redactions > 0


def _redact_for_langfuse(payload: Any, parent_key: str = "") -> tuple[Any, int]:
    """Redact common PII patterns before sending payloads to Langfuse."""
    key = (parent_key or "").lower()

    if isinstance(payload, dict):
        redacted_map: Dict[str, Any] = {}
        total = 0
        for child_key, child_value in payload.items():
            child_key_text = str(child_key)
            child_key_lower = child_key_text.lower()
            if any(token in child_key_lower for token in PII_KEYWORDS):
                redacted_map[child_key_text] = REDACTED_VALUE
                total += 1
                continue

            redacted_value, count = _redact_for_langfuse(child_value, child_key_text)
            redacted_map[child_key_text] = redacted_value
            total += count
        return redacted_map, total

    if isinstance(payload, list):
        redacted_list = []
        total = 0
        for item in payload:
            redacted_item, count = _redact_for_langfuse(item, parent_key)
            redacted_list.append(redacted_item)
            total += count
        return redacted_list, total

    if isinstance(payload, str):
        if any(token in key for token in PII_KEYWORDS):
            return REDACTED_VALUE, 1
        masked, changed = _mask_string_pii(payload)
        return masked, 1 if changed else 0

    return payload, 0


def _field_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _nested_get(payload: Dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _compute_required_fields_completeness(payload: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    checks = {
        "invoice_number": _field_present(_nested_get(payload, "invoice_details", "invoice_number")),
        "invoice_date": _field_present(_nested_get(payload, "invoice_details", "date")),
        "vendor_name": _field_present(_nested_get(payload, "vendor", "name")),
        "customer_name": _field_present(_nested_get(payload, "customer", "name")),
        "items_present": _field_present(_nested_get(payload, "items")),
        "summary_subtotal": _field_present(_nested_get(payload, "invoice_summary", "subtotal")),
        "summary_tax": _field_present(_nested_get(payload, "invoice_summary", "tax")),
        "summary_total": _field_present(_nested_get(payload, "invoice_summary", "total")),
    }

    total_checks = len(checks)
    passed_checks = sum(1 for passed in checks.values() if passed)
    score = (passed_checks / total_checks) if total_checks else 0.0
    return score, {
        "passed": passed_checks,
        "total": total_checks,
        "missing": [name for name, passed in checks.items() if not passed],
    }


def _is_close(a: float, b: float) -> bool:
    tolerance = max(0.5, 0.02 * max(abs(a), abs(b), 1.0))
    return abs(a - b) <= tolerance


def _compute_totals_consistency(payload: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else None
    items = items if isinstance(items, list) else []

    item_total_sum = 0.0
    item_subtotal_sum = 0.0
    item_total_count = 0
    item_subtotal_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        quantity = _to_float(item.get("quantity")) or 0.0
        unit_price = _to_float(item.get("unit_price")) or 0.0

        item_total = _to_float(item.get("total"))
        if item_total is not None:
            item_total_sum += item_total
            item_total_count += 1
        elif quantity and unit_price:
            item_total_sum += quantity * unit_price
            item_total_count += 1

        item_subtotal = _to_float(item.get("subtotal"))
        if item_subtotal is not None:
            item_subtotal_sum += item_subtotal
            item_subtotal_count += 1
        elif quantity and unit_price:
            item_subtotal_sum += quantity * unit_price
            item_subtotal_count += 1

    summary_subtotal = _to_float(_nested_get(payload, "invoice_summary", "subtotal"))
    summary_tax = _to_float(_nested_get(payload, "invoice_summary", "tax"))
    summary_total = _to_float(_nested_get(payload, "invoice_summary", "total"))

    checks: list[bool] = []
    details: Dict[str, Any] = {
        "summary_subtotal": summary_subtotal,
        "summary_tax": summary_tax,
        "summary_total": summary_total,
        "item_total_sum": item_total_sum if item_total_count else None,
        "item_subtotal_sum": item_subtotal_sum if item_subtotal_count else None,
    }

    if summary_total is not None and item_total_count > 0:
        checks.append(_is_close(summary_total, item_total_sum))

    if summary_subtotal is not None and item_subtotal_count > 0:
        checks.append(_is_close(summary_subtotal, item_subtotal_sum))

    if summary_subtotal is not None and summary_tax is not None and summary_total is not None:
        checks.append(_is_close(summary_subtotal + summary_tax, summary_total))

    if not checks:
        return 0.0, {
            **details,
            "reason": "insufficient_numeric_fields",
            "checks_passed": 0,
            "checks_total": 0,
        }

    passed = sum(1 for check in checks if check)
    return passed / len(checks), {
        **details,
        "checks_passed": passed,
        "checks_total": len(checks),
    }


def _start_langfuse_observation(
    langfuse_client: Any,
    *,
    model_name: str,
    image_name: str,
    metadata: Dict[str, Any],
):
    """Start a Langfuse observation with compatibility across SDK versions."""
    if langfuse_client is None:
        return nullcontext(None)

    # Newer SDK API
    if hasattr(langfuse_client, "start_as_current_observation"):
        return langfuse_client.start_as_current_observation(
            as_type="generation",
            name="invoice-extraction",
            model=model_name,
            input={"image_name": image_name},
            metadata=metadata,
        )

    # Legacy SDK API fallback
    try:
        legacy_trace = None
        legacy_generation = None

        if hasattr(langfuse_client, "trace"):
            legacy_trace = langfuse_client.trace(
                name="invoice-extraction",
                input={"image_name": image_name},
                metadata=metadata,
                user_id=metadata.get("langfuse_user_id"),
            )

        if legacy_trace is not None and hasattr(legacy_trace, "generation"):
            legacy_generation = legacy_trace.generation(
                name="invoice-extraction",
                model=model_name,
                input={"image_name": image_name},
                metadata=metadata,
            )
        elif hasattr(langfuse_client, "generation"):
            legacy_generation = langfuse_client.generation(
                name="invoice-extraction",
                model=model_name,
                input={"image_name": image_name},
                metadata=metadata,
            )

        if legacy_generation is not None:
            return nullcontext(legacy_generation)
    except Exception:
        logger.exception("Unable to start legacy Langfuse observation")

    return nullcontext(None)


def _update_langfuse_observation(
    observation: Any,
    *,
    response: Any,
    usage: Dict[str, int],
    estimated_cost_usd: float,
    metadata: Dict[str, Any],
) -> None:
    if observation is None:
        return

    payload = {
        "output": response,
        "usage_details": usage,
        "cost_details": {"total": estimated_cost_usd},
        "metadata": metadata,
    }

    # Newer SDK objects usually support update(...)
    if hasattr(observation, "update"):
        try:
            observation.update(**payload)
        except TypeError:
            # Legacy clients may have stricter kwargs
            try:
                observation.update(output=response, metadata=metadata)
            except Exception:
                logger.exception("Unable to update Langfuse observation")
        except Exception:
            logger.exception("Unable to update Langfuse observation")

    # Legacy SDK objects usually require explicit end(...)
    if hasattr(observation, "end"):
        try:
            observation.end(output=response)
        except TypeError:
            try:
                observation.end()
            except Exception:
                logger.exception("Unable to end Langfuse observation")
        except Exception:
            logger.exception("Unable to end Langfuse observation")

# Add title and description to the schema
FORMATTED_SCHEMA = {
    "title": "Invoice",
    "description": "A schema for invoice data extraction",
    **INVOICE_SCHEMA
}

class InvoiceProcessor:
    def __init__(self):
        self.model_name = "gpt-4o"
        base_model = ChatOpenAI(
            model=self.model_name,
            max_tokens=4096,
            temperature=0
        )

        # Configure model with structured output using the formatted schema
        self.model = base_model.with_structured_output(FORMATTED_SCHEMA)

        self.system_prompt = """You are an expert invoice analyzer. Your task is to extract information from invoice images
        and return it in a structured format. Be precise and thorough in your analysis. If you're unsure about any value,
        use null rather than making assumptions."""

        self.human_prompt = """Please analyze this invoice image and extract all relevant information.
        Return the data in a structured format. Be especially careful with numbers, dates, and calculations."""

    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64 string."""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def process_invoice(
        self,
        image_path: str,
        user_id: str | None = None,
        session_id: str | None = None,
        trace_metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Process an invoice image and return structured data."""
        # Verify image exists
        if not Path(image_path).exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Encode image
        base64_image = self._encode_image(image_path)

        # Create messages
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": self.human_prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            )
        ]

        tracer = trace.get_tracer(__name__)
        usage_callback = AIUsageCallbackHandler(model_name=self.model_name)
        langfuse_client = create_langfuse_client()

        base_trace_metadata = {
            "image_name": Path(image_path).name,
            "pipeline": "invoice-processing",
            "schema": "invoice",
        }
        base_trace_metadata.update(_trace_version_metadata())
        if trace_metadata:
            base_trace_metadata.update(trace_metadata)

        langfuse_metadata = build_langfuse_metadata(
            user_id=user_id,
            session_id=session_id,
            trace_name="invoice-extraction",
            tags=["invoice", "structured-output"],
            metadata=base_trace_metadata,
        )

        invoke_config = {"callbacks": [usage_callback]}
        start = time.perf_counter()

        # Get response from model and parse it to handle Unicode properly
        with tracer.start_as_current_span("ai.invoice_extraction") as span:
            span.set_attribute("ai.model", self.model_name)
            span.set_attribute("ai.input.image_path", str(Path(image_path).name))

            try:
                langfuse_context = _start_langfuse_observation(
                    langfuse_client,
                    model_name=self.model_name,
                    image_name=Path(image_path).name,
                    metadata=langfuse_metadata,
                )

                with langfuse_context as langfuse_observation:
                    response = self.model.invoke(messages, config=invoke_config)
                    duration_seconds = time.perf_counter() - start
                    usage = usage_callback.last_usage
                    estimated_cost_usd = observe_ai_cost(self.model_name, usage)
                    redacted_response, redacted_fields = _redact_for_langfuse(response)

                    _update_langfuse_observation(
                        langfuse_observation,
                        response=redacted_response,
                        usage=usage,
                        estimated_cost_usd=estimated_cost_usd,
                        metadata={
                            **langfuse_metadata,
                            "duration_seconds": duration_seconds,
                            "pii_redacted_fields": redacted_fields,
                        },
                    )

                observe_ai_request(self.model_name, "success", duration_seconds)
                observe_tokens_per_request(self.model_name, "success", usage)

                is_valid, validation_reason = validate_invoice_response(response)
                if not is_valid:
                    observe_parse_failure(self.model_name, validation_reason)
                    span.set_attribute("ai.parse.valid", False)
                    span.set_attribute("ai.parse.reason", validation_reason)
                else:
                    span.set_attribute("ai.parse.valid", True)

                submit_langfuse_score(
                    client=langfuse_client,
                    observation=langfuse_observation,
                    name="invoice_parse_valid",
                    value=1.0 if is_valid else 0.0,
                    comment=validation_reason,
                    metadata={
                        "schema": "invoice",
                        "model": self.model_name,
                    },
                )

                submit_langfuse_score(
                    client=langfuse_client,
                    observation=langfuse_observation,
                    name="invoice_extraction_success",
                    value=1.0,
                    metadata={
                        "duration_seconds": duration_seconds,
                        "image_name": Path(image_path).name,
                    },
                )

                submit_langfuse_score(
                    client=langfuse_client,
                    observation=langfuse_observation,
                    name="pii_redaction_applied",
                    value=1.0 if redacted_fields > 0 else 0.0,
                    metadata={
                        "redacted_fields": redacted_fields,
                        **_trace_version_metadata(),
                    },
                )

                totals_consistency_score, totals_details = _compute_totals_consistency(response)
                submit_langfuse_score(
                    client=langfuse_client,
                    observation=langfuse_observation,
                    name="totals_consistency",
                    value=totals_consistency_score,
                    metadata=totals_details,
                )

                required_fields_score, required_fields_details = _compute_required_fields_completeness(response)
                submit_langfuse_score(
                    client=langfuse_client,
                    observation=langfuse_observation,
                    name="required_fields_completeness",
                    value=required_fields_score,
                    metadata=required_fields_details,
                )

                span.set_attribute("ai.tokens.prompt", usage.get("prompt_tokens", 0))
                span.set_attribute("ai.tokens.completion", usage.get("completion_tokens", 0))
                span.set_attribute("ai.tokens.total", usage.get("total_tokens", 0))
                span.set_attribute("ai.cost.estimated_usd", estimated_cost_usd)
                span.set_attribute("ai.request.duration_seconds", duration_seconds)
            except Exception as exc:
                duration_seconds = time.perf_counter() - start
                observe_ai_request(self.model_name, "error", duration_seconds)
                observe_ai_error(self.model_name, type(exc).__name__)

                submit_langfuse_score(
                    client=langfuse_client,
                    observation=None,
                    name="invoice_extraction_success",
                    value=0.0,
                    comment=type(exc).__name__,
                    metadata={
                        "image_name": Path(image_path).name,
                        "error_type": type(exc).__name__,
                    },
                )

                span.record_exception(exc)
                span.set_attribute("ai.request.duration_seconds", duration_seconds)
                span.set_attribute("ai.error.type", type(exc).__name__)
                raise

        return response