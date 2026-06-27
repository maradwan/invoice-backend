import logging
import os
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)

try:
    from langfuse import get_client as _get_client
except ImportError:  # pragma: no cover - optional dependency guard
    _get_client = None

try:
    from langfuse import Langfuse as _Langfuse
except ImportError:  # pragma: no cover - optional dependency guard
    _Langfuse = None


def _clean_env(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned = value.strip()
    return cleaned or None


def _langfuse_base_url() -> Optional[str]:
    return _clean_env(os.getenv("LANGFUSE_BASE_URL")) or _clean_env(os.getenv("LANGFUSE_HOST"))


def _langfuse_keys_present() -> bool:
    return bool(
        _clean_env(os.getenv("LANGFUSE_PUBLIC_KEY"))
        and _clean_env(os.getenv("LANGFUSE_SECRET_KEY"))
    )


def _missing_langfuse_keys() -> list[str]:
    missing: list[str] = []
    if not _clean_env(os.getenv("LANGFUSE_PUBLIC_KEY")):
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not _clean_env(os.getenv("LANGFUSE_SECRET_KEY")):
        missing.append("LANGFUSE_SECRET_KEY")
    return missing


def configure_langfuse_environment() -> bool:
    """Normalize legacy/self-hosted Langfuse env vars for the SDK."""
    base_url = _langfuse_base_url()
    if base_url:
        os.environ.setdefault("LANGFUSE_BASE_URL", base_url)
        os.environ.setdefault("LANGFUSE_HOST", base_url)

    return _langfuse_keys_present()


def create_langfuse_client():
    """Return a Langfuse client when SDK and credentials are configured."""
    if _get_client is None and _Langfuse is None:
        logger.info("Langfuse disabled: langfuse package not importable")
        return None

    if not configure_langfuse_environment():
        missing_keys = _missing_langfuse_keys()
        logger.info(
            "Langfuse disabled: missing credentials (%s)",
            ", ".join(missing_keys) if missing_keys else "unknown",
        )
        return None

    try:
        if _get_client is not None:
            client = _get_client()
        else:
            base_url = _langfuse_base_url()
            kwargs: Dict[str, Any] = {
                "public_key": os.getenv("LANGFUSE_PUBLIC_KEY"),
                "secret_key": os.getenv("LANGFUSE_SECRET_KEY"),
            }
            if base_url:
                kwargs["base_url"] = base_url

            try:
                client = _Langfuse(**kwargs)
            except TypeError:
                # Older SDKs may expect `host` instead of `base_url`.
                if "base_url" in kwargs:
                    kwargs["host"] = kwargs.pop("base_url")
                client = _Langfuse(**kwargs)

        logger.info("Langfuse enabled")
        return client
    except Exception:
        logger.exception("Unable to initialize Langfuse client")
        return None


def build_langfuse_metadata(
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_name: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(metadata or {})

    if user_id:
        payload["langfuse_user_id"] = user_id
    if session_id:
        payload["langfuse_session_id"] = session_id
    if trace_name:
        payload["langfuse_trace_name"] = trace_name
    if tags:
        payload["langfuse_tags"] = tags

    return payload


def flush_langfuse() -> None:
    if (_get_client is None and _Langfuse is None) or not configure_langfuse_environment():
        return

    try:
        client = create_langfuse_client()
        if client is not None:
            client.flush()
    except Exception:
        logger.exception("Unable to flush Langfuse events")


def submit_langfuse_score(
    *,
    client: Any,
    observation: Any,
    name: str,
    value: float,
    comment: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Submit a score using whichever Langfuse scoring API is available."""
    if client is None:
        return False

    kwargs: Dict[str, Any] = {
        "name": name,
        "value": value,
    }
    if comment:
        kwargs["comment"] = comment
    if metadata:
        kwargs["metadata"] = metadata

    # Preferred when available on observation wrappers.
    if observation is not None and hasattr(observation, "score"):
        try:
            observation.score(**kwargs)
            return True
        except Exception:
            logger.exception("Unable to submit observation score via score()")

    if observation is not None and hasattr(observation, "score_trace"):
        try:
            observation.score_trace(**kwargs)
            return True
        except Exception:
            logger.exception("Unable to submit trace score via score_trace()")

    if hasattr(client, "score_current_trace"):
        try:
            client.score_current_trace(**kwargs)
            return True
        except Exception:
            logger.exception("Unable to submit score via score_current_trace()")

    trace_id = getattr(observation, "trace_id", None) if observation is not None else None
    if hasattr(client, "score") and trace_id:
        try:
            client.score(trace_id=trace_id, **kwargs)
            return True
        except TypeError:
            # Some SDK variants may expect a positional trace id.
            try:
                client.score(trace_id, **kwargs)
                return True
            except Exception:
                logger.exception("Unable to submit score via score(trace_id, ...)")
        except Exception:
            logger.exception("Unable to submit score via score(trace_id=...)")

    logger.info("Langfuse score skipped: no supported scoring API found")
    return False