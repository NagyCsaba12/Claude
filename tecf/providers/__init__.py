"""Mesterséges intelligencia szolgáltatók – név szerinti lista és egységes kliens.

Minden szolgáltató egy `ProviderSpec`. A legtöbb OpenAI-kompatibilis
(/chat/completions), az Anthropic, a Google Gemini és a Cohere saját
formátumot használ. Csak a Python standard könyvtárát használja (urllib),
így telepítés nélkül is működik.

API kulcs forrása (ebben a sorrendben):
  1. D:\\TecFAi\\config\\api_keys.json  ( `tecf keys set <név> <kulcs>` )
  2. környezeti változó (pl. OPENAI_API_KEY)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str            # rövid azonosító
    title: str           # megjelenített név
    style: str           # openai | anthropic | gemini | cohere
    base_url: str
    default_model: str
    env_key: str = ""    # üres = nem kell kulcs (helyi)
    local: bool = False
    note: str = ""


PROVIDERS: dict[str, ProviderSpec] = {p.name: p for p in [
    # ---- Helyi, offline futó motorok ----
    ProviderSpec("ollama", "Ollama (helyi)", "openai", "http://localhost:11434/v1", "qwen3:8b",
                 local=True, note="Offline. Telepítés: ollama.com, majd `ollama pull qwen3:8b`"),
    ProviderSpec("tecf-sajat", "TecF saját modell", "native", "", "sajat", local=True,
                 note="Saját, ezen a gépen tanított modell: tecf model build"),
    ProviderSpec("lmstudio", "LM Studio (helyi)", "openai", "http://localhost:1234/v1", "local-model", local=True),
    ProviderSpec("llamacpp", "llama.cpp server (helyi)", "openai", "http://localhost:8080/v1", "local-model",
                 local=True),
    ProviderSpec("localai", "LocalAI (helyi)", "openai", "http://localhost:8081/v1", "local-model", local=True),
    ProviderSpec("jan", "Jan (helyi)", "openai", "http://localhost:1337/v1", "local-model", local=True),
    # ---- Felhő szolgáltatók ----
    ProviderSpec("anthropic", "Anthropic Claude", "anthropic", "https://api.anthropic.com/v1",
                 "claude-sonnet-5", "ANTHROPIC_API_KEY"),
    ProviderSpec("openai", "OpenAI GPT", "openai", "https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    ProviderSpec("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta",
                 "gemini-2.0-flash", "GEMINI_API_KEY"),
    ProviderSpec("mistral", "Mistral AI", "openai", "https://api.mistral.ai/v1", "mistral-large-latest",
                 "MISTRAL_API_KEY"),
    ProviderSpec("cohere", "Cohere Command", "cohere", "https://api.cohere.com/v2", "command-r-plus",
                 "COHERE_API_KEY"),
    ProviderSpec("xai", "xAI Grok", "openai", "https://api.x.ai/v1", "grok-2-latest", "XAI_API_KEY"),
    ProviderSpec("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1", "deepseek-chat",
                 "DEEPSEEK_API_KEY"),
    ProviderSpec("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile",
                 "GROQ_API_KEY"),
    ProviderSpec("perplexity", "Perplexity (webes kereséssel)", "openai", "https://api.perplexity.ai", "sonar",
                 "PERPLEXITY_API_KEY"),
    ProviderSpec("together", "Together AI", "openai", "https://api.together.xyz/v1",
                 "meta-llama/Llama-3.3-70B-Instruct-Turbo", "TOGETHER_API_KEY"),
    ProviderSpec("openrouter", "OpenRouter (több száz modell egy kulccsal)", "openai",
                 "https://openrouter.ai/api/v1", "openrouter/auto", "OPENROUTER_API_KEY"),
    ProviderSpec("fireworks", "Fireworks AI", "openai", "https://api.fireworks.ai/inference/v1",
                 "accounts/fireworks/models/llama-v3p3-70b-instruct", "FIREWORKS_API_KEY"),
    ProviderSpec("cerebras", "Cerebras", "openai", "https://api.cerebras.ai/v1", "llama-3.3-70b",
                 "CEREBRAS_API_KEY"),
    ProviderSpec("huggingface", "Hugging Face Inference", "openai", "https://router.huggingface.co/v1",
                 "meta-llama/Llama-3.3-70B-Instruct", "HF_TOKEN"),
    ProviderSpec("nvidia", "NVIDIA NIM", "openai", "https://integrate.api.nvidia.com/v1",
                 "meta/llama-3.3-70b-instruct", "NVIDIA_API_KEY"),
    ProviderSpec("qwen", "Alibaba Qwen (DashScope)", "openai",
                 "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus", "DASHSCOPE_API_KEY"),
    ProviderSpec("moonshot", "Moonshot Kimi", "openai", "https://api.moonshot.ai/v1", "moonshot-v1-8k",
                 "MOONSHOT_API_KEY"),
    ProviderSpec("zhipu", "Zhipu GLM", "openai", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash",
                 "ZHIPU_API_KEY"),
    ProviderSpec("ai21", "AI21 Jamba", "openai", "https://api.ai21.com/studio/v1", "jamba-large",
                 "AI21_API_KEY"),
    ProviderSpec("sambanova", "SambaNova", "openai", "https://api.sambanova.ai/v1", "Meta-Llama-3.3-70B-Instruct",
                 "SAMBANOVA_API_KEY"),
    ProviderSpec("azure", "Azure OpenAI", "openai", "", "gpt-4o", "AZURE_OPENAI_API_KEY",
                 note="base_url: https://<erőforrás>.openai.azure.com/openai/deployments/<név> (keys.json: azure_url)"),
]}


class ProviderError(RuntimeError):
    pass


class Cancelled(Exception):
    """A felhasználó leállította a választ. `partial`: az addig elkészült szöveg."""

    def __init__(self, partial: str = ""):
        super().__init__("leállítva")
        self.partial = partial


def _check(cancel, partial: str = "") -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled(partial)


def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ProviderError(f"Nem elérhető: {e}") from e


def _stream_openai(url: str, payload: dict, headers: dict, timeout: float, cancel, on_token) -> str:
    """Folyamatos (darabonkénti) válasz. Leállításkor a kapcsolat bezárul, így a modell is abbahagyja."""
    req = urllib.request.Request(url, data=json.dumps({**payload, "stream": True}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                _check(cancel, "".join(parts))
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    choices = json.loads(data).get("choices") or []
                except json.JSONDecodeError:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") if choices else None
                if delta:
                    parts.append(delta)
                    if on_token:
                        on_token(delta)
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ProviderError(f"Nem elérhető: {e}") from e
    return "".join(parts)


class Provider:
    """Egységes chat kliens bármely listázott szolgáltatóhoz."""

    def __init__(self, spec: ProviderSpec, api_key: str = "", model: str | None = None,
                 base_url: str | None = None, timeout: float = 120):
        self.spec = spec
        self.api_key = api_key
        self.model = model or spec.default_model
        self.base_url = (base_url or spec.base_url).rstrip("/")
        self.timeout = timeout

    @property
    def label(self) -> str:
        return f"{self.spec.name}:{self.model}"

    def _own_root(self):
        from pathlib import Path

        from tecf.config import Config
        return Path(self.base_url) if self.base_url else Config.load().root / "sajat_modell"

    def available(self) -> bool:
        if self.spec.style == "native":
            try:
                import torch  # noqa: F401
            except ImportError:
                return False
            root = self._own_root()
            return (root / "alap" / "modell" / "config.json").exists() or (root / "model.pt").exists()
        if self.spec.local:
            try:
                urllib.request.urlopen(self.base_url + "/models", timeout=2)
                return True
            except Exception:
                return False
        return bool(self.api_key) and bool(self.base_url)

    def chat(self, messages: list[dict], system: str = "", temperature: float = 0.3,
             max_tokens: int = 2048, cancel=None, on_token=None) -> str:
        """`cancel`: threading.Event – ha beállítják, a válasz leáll (Cancelled kivétel).
        `on_token`: a válasz darabjait kapja meg, amint megérkeznek (élő megjelenítéshez)."""
        _check(cancel)
        text = self._chat(messages, system, temperature, max_tokens, cancel, on_token)
        _check(cancel, text)
        return text

    def _chat(self, messages, system, temperature, max_tokens, cancel, on_token) -> str:
        style = self.spec.style
        if style == "native":
            root = self._own_root()
            try:
                if (root / "alap" / "modell" / "config.json").exists():  # alaptudással indított saját modell
                    from tecf.llm.base import BaseModelRunner
                    return BaseModelRunner.get(root / "alap" / "modell").chat(messages, system, temperature,
                                                                               max_tokens, cancel)
                from tecf.llm.infer import OwnModel  # nulláról tanított saját modell
                return OwnModel.get(root).chat(messages, system, max(temperature, 0.5), min(max_tokens, 400),
                                               cancel)
            except Cancelled:
                raise
            except Exception as e:
                raise ProviderError(f"Saját modell hiba: {e}") from e
        if style == "anthropic":
            data = _post(f"{self.base_url}/messages",
                         {"model": self.model, "system": system, "messages": messages,
                          "max_tokens": max_tokens, "temperature": temperature},
                         {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, self.timeout)
            return "".join(b.get("text", "") for b in data.get("content", []))
        if style == "gemini":
            contents = [{"role": "model" if m["role"] == "assistant" else "user",
                         "parts": [{"text": m["content"]}]} for m in messages]
            payload = {"contents": contents, "generationConfig": {"temperature": temperature,
                                                                  "maxOutputTokens": max_tokens}}
            if system:
                payload["systemInstruction"] = {"parts": [{"text": system}]}
            data = _post(f"{self.base_url}/models/{self.model}:generateContent", payload,
                         {"x-goog-api-key": self.api_key}, self.timeout)
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        if style == "cohere":
            data = _post(f"{self.base_url}/chat",
                         {"model": self.model, "messages": msgs, "temperature": temperature},
                         {"Authorization": f"Bearer {self.api_key}"}, self.timeout)
            return "".join(c.get("text", "") for c in data["message"]["content"])
        headers = {"api-key": self.api_key} if self.spec.name == "azure" else (
            {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
        url = f"{self.base_url}/chat/completions"
        if self.spec.name == "azure":
            url += "?api-version=2024-10-21"
        payload = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
        if cancel is not None or on_token is not None:
            return _stream_openai(url, payload, headers, self.timeout, cancel, on_token)
        data = _post(url, payload, headers, self.timeout)
        return data["choices"][0]["message"]["content"]


def get_provider(name: str, keys: dict[str, str] | None = None, model: str | None = None) -> Provider:
    """`name` lehet 'openai' vagy 'openai:gpt-4o' formájú is."""
    if ":" in name and model is None:
        name, model = name.split(":", 1)
    spec = PROVIDERS.get(name)
    if spec is None:
        raise ProviderError(f"Ismeretlen szolgáltató: {name}. Lista: tecf providers")
    keys = keys or {}
    key = keys.get(name) or (os.environ.get(spec.env_key, "") if spec.env_key else "")
    base = keys.get(f"{name}_url") or None
    if spec.style == "native":
        model = spec.default_model
    return Provider(spec, key, model or keys.get(f"{name}_model"), base)
