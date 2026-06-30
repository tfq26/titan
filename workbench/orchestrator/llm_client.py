"""
Shared LLM client for the workbench orchestrator.

Provides a single interface for calling LLMs across providers
(Anthropic, OpenAI, OpenAI-compatible, Google) with structured output
support.

Configuration is read from routing.yaml:
  models:   Registry of model configs (nickname, model_id, provider, env vars)
  roles:    Maps each workflow role to a model via model_ref

Resolution path: role → model_ref → model config → provider → LLM client.

Usage:
    from .llm_client import call_llm

    result = call_llm(role="classifier", system_prompt="...",
                      user_prompt="...", output_schema=MyModel)
"""

from __future__ import annotations

import json
import os
import time
import logging
from pathlib import Path
from typing import Optional, Type, TypeVar, Generator

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Routing config cache ──────────────────────────────────────────────

_routing_cache: Optional[dict] = None


def _load_routing() -> dict:
    """Load routing.yaml, caching the result."""
    global _routing_cache
    if _routing_cache is not None:
        return _routing_cache

    vault_root = Path(__file__).resolve().parent.parent
    routing_path = vault_root / "model-routing" / "routing.yaml"

    if routing_path.exists():
        with open(routing_path) as f:
            _routing_cache = yaml.safe_load(f)
        return _routing_cache

    logger.warning("routing.yaml not found at %s, using empty config", routing_path)
    _routing_cache = {"models": {}, "roles": {}}
    return _routing_cache


# ── Model registry resolution ─────────────────────────────────────────

def _get_model_config(model_ref: str) -> dict:
    """
    Resolve a model_ref to its full model config from the registry.

    Args:
        model_ref: Key in the models section of routing.yaml

    Returns:
        The model config dict, or an empty dict if not found.

    Raises:
        KeyError: If model_ref is not found in the registry.
    """
    routing = _load_routing()
    models = routing.get("models", {})

    if model_ref not in models:
        available = list(models.keys())
        raise KeyError(
            f"Model ref '{model_ref}' not found in routing.yaml models registry. "
            f"Available models: {available or '(none)'}"
        )

    return models[model_ref]


def _resolve_role(role: str) -> dict:
    """
    Resolve a role name to its full model config.

    Resolution path: role → model_ref (from roles section) → model config.

    Args:
        role: Role name (e.g. "classifier", "primary_reviewer")

    Returns:
        The resolved model config dict with model_ref injected.

    Raises:
        KeyError: If role or model_ref is missing.
        ValueError: If env vars are missing for the model.
    """
    routing = _load_routing()
    roles = routing.get("roles", {})

    if role not in roles:
        available = list(roles.keys())
        raise KeyError(
            f"Role '{role}' not found in routing.yaml. "
            f"Available roles: {available or '(none)'}"
        )

    role_config = roles[role]
    model_ref = role_config.get("model_ref", "")

    if not model_ref:
        raise KeyError(
            f"Role '{role}' has no model_ref. Roles must reference a model "
            f"from the models registry via model_ref."
        )

    model_config = dict(_get_model_config(model_ref))

    # Inject the model_ref so callers can trace it (on a copy)
    model_config["_model_ref"] = model_ref

    # Validate required env vars
    _validate_env_vars(model_config)

    return model_config


# ── Public resolve helpers (used by run.py) ───────────────────────────

def resolve_role_nickname(role: str) -> str:
    """Return the nickname for a role, or the role name if unresolvable."""
    try:
        config = _resolve_role(role)
        return config.get("nickname", config.get("model_id", role))
    except Exception:
        return role


def resolve_role_model_id(role: str) -> str:
    """Return the backend model_id for a role, or empty string if unresolvable."""
    try:
        config = _resolve_role(role)
        return config.get("model_id", "")
    except Exception:
        return ""


# ── Error types ────────────────────────────────────────────────────────

class EnvVarError(Exception):
    """Raised when required environment variables are not set.

    This is a CONFIGURATION error — distinct from provider/API failures
    (which are runtime errors) and policy denials (which are authorization
    errors). Fix the env vars and restart — no retry loop needed.
    """
    pass


# ── Env var validation ────────────────────────────────────────────────

def _validate_env_vars(model_config: dict) -> None:
    """Check that required env vars are set. Raises EnvVarError if missing."""
    api_key_env = model_config.get("api_key_env", "")
    base_url_env = model_config.get("base_url_env", "")

    missing = []

    if api_key_env and not os.environ.get(api_key_env):
        missing.append(api_key_env)

    if base_url_env and not os.environ.get(base_url_env):
        missing.append(base_url_env)

    if missing:
        nickname = model_config.get("nickname", model_config.get("model_id", "unknown"))
        raise EnvVarError(
            f"Missing required environment variables for model '{nickname}': "
            f"{', '.join(missing)}. Set them before running the orchestrator."
        )


# ── Provider dispatch ─────────────────────────────────────────────────

def _get_chat_model(
    role: str,
    *,
    project_policy: dict | None = None,
    project_id: str = "",
):
    """
    Return a LangChain chat model instance for the given role.

    Also enforces project model policy (static checks) if a policy
    is provided. ModelPolicyError propagates up — it is NOT caught here.

    Supported providers: anthropic, openai, openai_compatible, google
    """
    config = _resolve_role(role)

    model_id = config.get("model_id", "")
    provider = config.get("provider", "anthropic")
    temperature = config.get("temperature", 0.1)
    max_tokens = config.get("max_tokens", 4096)
    nickname = config.get("nickname", model_id)
    model_ref = config.get("_model_ref", "")

    if not model_id:
        raise ValueError(
            f"No model_id configured for role '{role}' (model '{nickname}')"
        )

    # ── Enforce project model policy (static) ────────────────────────
    if project_policy is not None:
        from .model_policy import validate_role_access
        validate_role_access(
            role, model_ref,
            policy=project_policy, project_id=project_id,
        )

    # ── Anthropic ───────────────────────────────────────────────────
    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain_anthropic is required for Anthropic models. "
                "Install with: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── OpenAI ──────────────────────────────────────────────────────
    elif provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain_openai is required for OpenAI models. "
                "Install with: pip install langchain-openai"
            )
        return ChatOpenAI(
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── OpenAI-compatible (custom endpoint) ─────────────────────────
    elif provider == "openai_compatible":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain_openai is required for OpenAI-compatible models. "
                "Install with: pip install langchain-openai"
            )

        base_url_env = config.get("base_url_env", "")
        api_key_env = config.get("api_key_env", "")

        base_url = os.environ.get(base_url_env, "")
        api_key = os.environ.get(api_key_env, "")

        if not base_url:
            raise ValueError(
                f"base_url_env '{base_url_env}' is set but the env var is empty "
                f"for model '{nickname}'. Set {base_url_env} to your endpoint URL."
            )
        if not api_key:
            raise ValueError(
                f"api_key_env '{api_key_env}' is set but the env var is empty "
                f"for model '{nickname}'. Set {api_key_env} to your API key."
            )

        logger.info(
            "llm_client openai_compatible model=%s nickname=%s base_url=%s",
            model_id, nickname, base_url[:40] + "..." if len(base_url) > 40 else base_url,
        )

        return ChatOpenAI(
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            api_key=api_key,
        )

    # ── Google ──────────────────────────────────────────────────────
    elif provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "langchain_google_genai is required for Google models. "
                "Install with: pip install langchain-google-genai"
            )
        return ChatGoogleGenerativeAI(
            model=model_id,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    else:
        raise ValueError(
            f"Unknown provider '{provider}' for model '{nickname}' (role '{role}'). "
            f"Supported: anthropic, openai, openai_compatible, google"
        )


# ── Structured LLM call ───────────────────────────────────────────────

def call_llm(
    role: str,
    system_prompt: str,
    user_prompt: str,
    output_schema: Type[T],
    *,
    fallback: Optional[T] = None,
    project_policy: Optional[dict] = None,
    project_id: str = "",
    policy_ctx: Optional[dict] = None,
) -> T:
    """
    Call an LLM for the given role with structured output.

    Args:
        role: Role name (e.g. "classifier", "primary_reviewer")
        system_prompt: System-level instructions
        user_prompt: The main prompt / context to process
        output_schema: Pydantic model class for structured output parsing
        fallback: Value to return if the LLM call or parsing fails
        project_policy: Project model_policy dict (from project-config.yaml).
                        If provided, static and runtime validation runs before
                        invocation. ModelPolicyError propagates — it is NOT
                        caught here so callers can distinguish policy denials
                        from LLM failures.
        project_id: Project identifier for error messages and traces
        policy_ctx: Runtime context for role_requirements validation
                    (e.g. {'escalation_tier': 'high', 'task_type': 'implementation'})

    Returns:
        Parsed structured output as an instance of output_schema.

    Raises:
        ModelPolicyError: If the invocation is denied by project policy.
                          Callers MUST catch this and route to blocked/approval.
    """
    nickname = resolve_role_nickname(role)
    prompt_chars = len(system_prompt) + len(user_prompt)
    start = time.time()

    from .tracing import trace_llm_call

    # ── Policy enforcement (propagates on failure) ───────────────────
    if project_policy is not None:
        from .model_policy import validate_model_invocation
        config = _resolve_role(role)
        model_ref = config.get("_model_ref", "")
        validate_model_invocation(
            role=role,
            model_ref=model_ref,
            policy=project_policy,
            project_id=project_id,
            runtime_context=policy_ctx,
        )

    try:
        chat_model = _get_chat_model(
            role,
            project_policy=project_policy,
            project_id=project_id,
        )
        structured_model = chat_model.with_structured_output(output_schema)

        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        with trace_llm_call(role, nickname, prompt_chars) as trace_span:
            result = structured_model.invoke(messages)
            elapsed = time.time() - start

            if hasattr(result, "usage_metadata"):
                usage = result.usage_metadata
                trace_span.set_metadata("input_tokens", usage.get("input_tokens", 0))
                trace_span.set_metadata("output_tokens", usage.get("output_tokens", 0))

        logger.info(
            "llm_call role=%s model=%s latency=%.2fs",
            role, nickname, elapsed,
        )

        if not isinstance(result, output_schema):
            logger.warning(
                "llm_call role=%s model=%s returned unexpected type %s, "
                "attempting manual parse",
                role, nickname, type(result).__name__,
            )
            if isinstance(result, dict):
                result = output_schema(**result)
            elif isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    result = output_schema(**parsed)
                except (json.JSONDecodeError, Exception):
                    if fallback is not None:
                        return fallback
                    raise

        return result

    except Exception as exc:
        elapsed = time.time() - start
        logger.error(
            "llm_call role=%s model=%s latency=%.2fs error=%s",
            role, nickname, elapsed, exc,
        )
        if fallback is not None:
            logger.warning(
                "llm_call role=%s returning fallback after error", role
            )
            return fallback
        raise


# ── Convenience: call without structured output ───────────────────────

def call_llm_text(
    role: str,
    system_prompt: str,
    user_prompt: str,
    *,
    fallback: Optional[str] = None,
    project_policy: Optional[dict] = None,
    project_id: str = "",
    policy_ctx: Optional[dict] = None,
    token_usage: Optional[dict] = None,
) -> str:
    """
    Call an LLM for the given role, returning plain text.

    ModelPolicyError propagates — callers must catch it.
    """
    nickname = resolve_role_nickname(role)
    prompt_chars = len(system_prompt) + len(user_prompt)
    start = time.time()

    from .tracing import trace_llm_call

    # ── Policy enforcement (propagates on failure) ───────────────────
    if project_policy is not None:
        from .model_policy import validate_model_invocation
        config = _resolve_role(role)
        model_ref = config.get("_model_ref", "")
        validate_model_invocation(
            role=role,
            model_ref=model_ref,
            policy=project_policy,
            project_id=project_id,
            runtime_context=policy_ctx,
        )

    try:
        chat_model = _get_chat_model(
            role,
            project_policy=project_policy,
            project_id=project_id,
        )
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        with trace_llm_call(role, nickname, prompt_chars) as trace_span:
            response = chat_model.invoke(messages)
            elapsed = time.time() - start

            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                trace_span.set_metadata("input_tokens", usage.get("input_tokens", 0))
                trace_span.set_metadata("output_tokens", usage.get("output_tokens", 0))
                if token_usage is not None:
                    token_usage["input_tokens"] = usage.get("input_tokens", 0)
                    token_usage["output_tokens"] = usage.get("output_tokens", 0)

        logger.info(
            "llm_call_text role=%s model=%s latency=%.2fs",
            role, nickname, elapsed,
        )

        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts) if text_parts else str(content)
        return content

    except Exception as exc:
        elapsed = time.time() - start
        logger.error(
            "llm_call_text role=%s model=%s latency=%.2fs error=%s",
            role, nickname, elapsed, exc,
        )
        if fallback is not None:
            return fallback
        raise


# ── Streaming LLM call (text only) ───────────────────────────────────

def call_llm_text_stream(
    role: str,
    system_prompt: str,
    user_prompt: str,
    *,
    fallback: Optional[str] = None,
    project_policy: Optional[dict] = None,
    project_id: str = "",
    policy_ctx: Optional[dict] = None,
    token_usage: Optional[dict] = None,
) -> Generator[str, None, str]:
    """
    Stream an LLM call token by token.

    Yields each text token as it arrives from the model.
    Returns the full response text when iteration completes.

    ModelPolicyError propagates — callers must catch it.
    """
    nickname = resolve_role_nickname(role)
    prompt_chars = len(system_prompt) + len(user_prompt)
    start = time.time()

    from .tracing import trace_llm_call

    # ── Policy enforcement (propagates on failure) ───────────────────
    if project_policy is not None:
        from .model_policy import validate_model_invocation
        config = _resolve_role(role)
        model_ref = config.get("_model_ref", "")
        validate_model_invocation(
            role=role,
            model_ref=model_ref,
            policy=project_policy,
            project_id=project_id,
            runtime_context=policy_ctx,
        )

    try:
        chat_model = _get_chat_model(
            role,
            project_policy=project_policy,
            project_id=project_id,
        )
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        full_content_parts: list[str] = []

        with trace_llm_call(role, nickname, prompt_chars) as trace_span:
            for chunk in chat_model.stream(messages):
                token = _extract_text_token(chunk)
                if token:
                    full_content_parts.append(token)
                    yield token

            elapsed = time.time() - start
            # Extract token usage from stream last chunk
            # Google Gemini stores usage_metadata = None on stream chunks
            # OpenAI/Anthropic populate usage_metadata with {input_tokens, output_tokens}
            if token_usage is not None:
                usage = None
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata is not None:
                    usage = chunk.usage_metadata
                if usage is not None:
                    token_usage["input_tokens"] = usage.get("input_tokens", 0)
                    token_usage["output_tokens"] = usage.get("output_tokens", 0)
                    trace_span.set_metadata("input_tokens", usage.get("input_tokens", 0))
                    trace_span.set_metadata("output_tokens", usage.get("output_tokens", 0))
                else:
                    # Fallback: estimate from accumulated text
                    full_text = "".join(full_content_parts)
                    char_count = len(full_text)
                    trace_span.set_metadata("output_tokens", char_count)
                    token_usage["input_tokens"] = 0
                    token_usage["output_tokens"] = char_count

        logger.info(
            "llm_call_text_stream role=%s model=%s latency=%.2fs",
            role, nickname, elapsed,
        )

        return "".join(full_content_parts)

    except Exception as exc:
        elapsed = time.time() - start
        logger.error(
            "llm_call_text_stream role=%s model=%s latency=%.2fs error=%s",
            role, nickname, elapsed, exc,
        )
        if fallback is not None:
            return fallback
        raise


def _extract_text_token(chunk) -> str:
    """Extract text content from an LLM stream chunk."""
    if hasattr(chunk, "content") and chunk.content:
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
                elif isinstance(part, str):
                    parts.append(part)
            return "".join(parts)
    return ""
