"""Bounded OpenAI-compatible model gateway with sensitivity-aware fallback."""
import json
import math
import os
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from innovation import RULES, STATE, SafeRedirect, safe_feed_url


class GatewayError(RuntimeError):
    pass


class PolicyBlocked(GatewayError):
    pass


class GatewayUnavailable(GatewayError):
    pass


def sensitive_rules(messages):
    encoded = json.dumps(messages, ensure_ascii=False)
    return [name for name, pattern in RULES if pattern.search(encoded)]


def endpoint_is_valid(provider):
    parts = urlsplit(provider.get("base_url", ""))
    host = (parts.hostname or "").lower()
    if parts.username or parts.password:
        return False
    if provider.get("local", False):
        return not parts.username and not parts.password and parts.scheme in {"http", "https"} and host in {"localhost", "127.0.0.1", "::1"}
    return safe_feed_url(provider.get("base_url", ""))


class OpenAICompatibleTransport:
    def __call__(self, provider, messages, max_tokens, timeout):
        base = provider["base_url"].rstrip("/")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        key_env = provider.get("api_key_env")
        if key_env:
            key = os.environ.get(key_env)
            if not key:
                raise OSError("provider credential unavailable")
            headers["Authorization"] = "Bearer " + key
        payload = {"model": provider["model"], "messages": messages, "max_tokens": max_tokens}
        if provider.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        opener = urllib.request.build_opener(SafeRedirect)
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("provider response exceeds size limit")
        return json.loads(raw.decode("utf-8"))


class Gateway:
    def __init__(self, config, transport=None, state_dir=None):
        providers = config.get("providers", [])
        concurrency = int(config.get("max_concurrency", 2))
        if not isinstance(providers, list) or len(providers) > 40 or concurrency < 1 or concurrency > 32:
            raise ValueError("invalid gateway provider or concurrency configuration")
        if any(not isinstance(provider, dict) for provider in providers):
            raise ValueError("each gateway provider must be an object")
        self.config = config
        self.transport = transport or OpenAICompatibleTransport()
        self.state_dir = Path(state_dir or STATE)
        self.requests = 0
        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self.guard = threading.Lock()
        self.slots = threading.BoundedSemaphore(int(config.get("max_concurrency", 2)))

    def _log(self, event):
        path = self.state_dir / "gateway" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if os.name != "nt":
            path.parent.chmod(0o700)
            path.chmod(0o600)

    def _eligible(self, task, messages, sensitivity, allow_sensitive_external):
        detected = sensitive_rules(messages)
        level = "sensitive" if detected else sensitivity
        if level not in {"public", "internal", "sensitive"}:
            raise PolicyBlocked("invalid sensitivity classification")
        candidates = []
        for provider in self.config.get("providers", []):
            if not provider.get("enabled", False) or not endpoint_is_valid(provider):
                continue
            if task not in provider.get("tasks", []) and "*" not in provider.get("tasks", []):
                continue
            if not provider.get("local", False) and not provider.get("api_key_env"):
                continue
            if not provider.get("local", False) and not os.environ.get(provider["api_key_env"]):
                continue
            if not provider.get("local", False):
                if level == "sensitive" and not (allow_sensitive_external and provider.get("sensitive_authorized") and provider.get("retention_reviewed_at")):
                    continue
                if level == "internal" and "internal" not in provider.get("allowed_sensitivity", ["public"]):
                    continue
                if level == "sensitive" and "sensitive" not in provider.get("allowed_sensitivity", []):
                    continue
            candidates.append(provider)
        candidates.sort(key=lambda item: float(item.get("input_cost_per_million", 1e12)) + float(item.get("output_cost_per_million", 1e12)))
        if not candidates:
            self._log({"time": time.time(), "event": "blocked", "task": task,
                       "sensitivity": level, "detectors": detected, "reason": "no_eligible_provider"})
            raise PolicyBlocked("no configured provider is eligible for this task and data class")
        return level, detected, candidates

    def complete(self, task, messages, *, sensitivity="public", allow_sensitive_external=False,
                 required_capabilities=(), max_tokens=1000):
        if not self.slots.acquire(blocking=False):
            raise GatewayError("concurrency limit reached")
        try:
            return self._complete(task, messages, sensitivity, allow_sensitive_external,
                                  set(required_capabilities), max_tokens)
        finally:
            self.slots.release()

    def _complete(self, task, messages, sensitivity, allow_sensitive_external, required_capabilities, max_tokens):
        level, detected, candidates = self._eligible(task, messages, sensitivity, allow_sensitive_external)
        candidates = [p for p in candidates if required_capabilities.issubset(set(p.get("capabilities", [])))]
        max_attempts = min(3, max(1, int(self.config.get("max_attempts", 2))))
        max_requests = int(self.config.get("max_requests_per_run", 20))
        max_spend = float(self.config.get("max_cost_usd_per_run", 0))
        if max_requests < 1 or not math.isfinite(max_spend) or max_spend < 0:
            raise GatewayError("request or spend limits are invalid")
        max_tokens = min(max(1, int(max_tokens)), int(self.config.get("max_output_tokens", 4000)))
        if max_tokens < 1:
            raise GatewayError("output token limit is invalid")
        if not candidates:
            raise PolicyBlocked("no provider supports the requested capabilities")
        request_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        max_input_bytes = int(self.config.get("max_input_bytes", 200_000))
        if request_bytes > max_input_bytes:
            raise GatewayError("input size limit reached")
        request_id = str(uuid.uuid4())
        failures = []
        for index, provider in enumerate(candidates[:max_attempts], start=1):
            with self.guard:
                if self.requests >= max_requests:
                    self._log({"time": time.time(), "event": "blocked", "task": task, "reason": "request_limit"})
                    raise GatewayError("request limit reached")
                rates = (float(provider.get("input_cost_per_million", 1e12)),
                         float(provider.get("output_cost_per_million", 1e12)))
                if any(not math.isfinite(rate) or rate < 0 for rate in rates):
                    raise GatewayError("provider cost configuration is invalid")
                estimated = (request_bytes * rates[0] + max_tokens * rates[1]) / 1_000_000
                if self.spent_usd + self.reserved_usd + estimated > max_spend:
                    self._log({"time": time.time(), "event": "blocked", "task": task,
                               "provider": provider["id"], "reason": "estimated_spend_limit"})
                    raise GatewayError("estimated spend limit reached")
                self.requests += 1
                self.reserved_usd += estimated
            start = time.monotonic()
            try:
                response = self.transport(provider, messages, max_tokens, int(self.config.get("timeout_seconds", 30)))
                choice = response["choices"][0]["message"]["content"]
                usage = response.get("usage", {})
                input_tokens = int(usage.get("prompt_tokens", request_bytes))
                output_tokens = int(usage.get("completion_tokens", max_tokens))
                cost = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
                with self.guard:
                    self.reserved_usd = max(0.0, self.reserved_usd - estimated)
                    self.spent_usd += cost
                try:
                    self._log({"time": time.time(), "request_id": request_id, "event": "success",
                               "task": task, "sensitivity": level, "detectors": detected,
                               "provider": provider["id"], "model": provider["model"], "attempt": index,
                               "latency_ms": round((time.monotonic() - start) * 1000),
                               "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 8)})
                except OSError as exc:
                    raise GatewayError("gateway audit logging failed") from exc
                return {"content": choice, "provider": provider["id"], "model": provider["model"],
                        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}}
            except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                with self.guard:
                    self.reserved_usd = max(0.0, self.reserved_usd - estimated)
                    self.spent_usd += estimated
                category = type(exc).__name__
                failures.append(category)
                self._log({"time": time.time(), "request_id": request_id, "event": "failure",
                           "task": task, "sensitivity": level, "provider": provider["id"],
                           "model": provider["model"], "attempt": index, "error": category,
                           "estimated_cost_usd": round(estimated, 8), "charge_unknown": True})
        raise GatewayUnavailable("all eligible provider attempts failed: " + ", ".join(failures))
