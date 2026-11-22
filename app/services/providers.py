
import json
import random
import re
import time
import requests
from urllib.parse import urlparse

from app.config import GROQ_URL, TAVILY_URL


# ============================================================
# PROVIDER ERROR
# ============================================================

class ProviderError(RuntimeError):

    def __init__(self, provider, message, status_code=None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


# ============================================================
# HTTP WITH EXPONENTIAL BACKOFF (rate limits / transient 5xx)
# ============================================================

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRY_WAIT = 45          # never sleep longer than this for one retry (seconds)


def _retry_after_seconds(response):
    """Seconds requested by the server's Retry-After header, or None."""
    try:
        value = response.headers.get("Retry-After")
    except Exception:  # noqa: BLE001 - a mocked/odd response must not break retries
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _backoff_delay(attempt, retry_after=None, base=2.0):
    """base * 2**attempt (+ up to 25% jitter), but at least what the server asked for; capped."""
    delay = base * (2 ** attempt)
    delay += random.uniform(0, delay * 0.25)
    if retry_after is not None:
        delay = max(delay, retry_after)
    return min(delay, MAX_RETRY_WAIT)


def _post(url, retries=3, **kwargs):
    """POST with exponential backoff on 429/5xx and transient network errors.

    Honours Retry-After. After the last attempt the final response is returned so the caller can
    turn it into a precise ProviderError; a persistent network error is re-raised.
    """
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, **kwargs)
        except requests.RequestException:
            if attempt < retries:
                time.sleep(_backoff_delay(attempt))
                continue
            raise
        if response.status_code in RETRY_STATUSES and attempt < retries:
            time.sleep(_backoff_delay(attempt, _retry_after_seconds(response)))
            continue
        return response


# ============================================================
# GROQ AI JSON RESPONSE
# ============================================================

def groq_json(prompt, key, model, system, max_tokens=650):

    if not key:
        raise ProviderError(
            "Groq",
            "Groq API key is missing."
        )

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    messages = [
        {
            "role": "system",
            "content": system
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": min(4096, max(256, int(max_tokens))),
        "temperature": 0,
    }

    # GPT-OSS specific settings
    if model.startswith("openai/gpt-oss"):

        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False

    try:

        response = _post(
            GROQ_URL,
            headers=headers,
            json=payload,
            timeout=(10, 90)
        )

    except requests.RequestException as e:

        raise ProviderError(
            "Groq",
            f"Network error: {e}"
        ) from e

    # HTTP error handling
    if response.status_code == 401:

        raise ProviderError(
            "Groq",
            "Groq API key rejected. Check your API key.",
            401
        )

    if response.status_code == 403:

        raise ProviderError(
            "Groq",
            "Model access denied.",
            403
        )

    if response.status_code == 429:

        raise ProviderError(
            "Groq",
            "Groq rate limit or token quota reached.",
            429
        )

    if response.status_code == 413:

        raise ProviderError(
            "Groq",
            "Request payload is too large.",
            413
        )

    if response.status_code >= 400:

        raise ProviderError(
            "Groq",
            f"Groq API returned HTTP {response.status_code}.",
            response.status_code
        )

    # Parse response
    try:

        data = response.json()

        choices = data.get("choices", [])

        if not choices:
            raise ValueError(
                "Groq returned no choices."
            )

        choice = choices[0]
        message = choice.get("message", {})

        raw = message.get("content")

        # Diagnose empty response
        if not raw or not raw.strip():

            finish_reason = choice.get("finish_reason")
            usage = data.get("usage", {})

            raise ValueError(
                "Groq returned empty content. "
                f"Finish reason: {finish_reason}. "
                f"Token usage: {usage}"
            )

        raw = raw.strip()

        # Remove Markdown code fences
        raw = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            raw,
            flags=re.I
        ).strip()

        # Direct JSON parsing
        try:

            result = json.loads(raw)

        except json.JSONDecodeError:

            first = raw.find("{")
            last = raw.rfind("}")

            if first == -1 or last <= first:

                raise ValueError(
                    "No valid JSON object found in model response."
                )

            result = json.loads(
                raw[first:last + 1]
            )

        if not isinstance(result, dict):

            raise ValueError(
                "Expected a JSON object from Groq."
            )

        return result

    except Exception as e:

        raise ProviderError(
            "Groq",
            f"Invalid model response: {e}"
        ) from e


# ============================================================
# SOURCE CLASSIFICATION
# ============================================================

# Primary / institutional sources. Used to build the authority-only fallback search too.
AUTHORITY_DOMAINS = (
    "who.int", "worldbank.org", "imf.org", "un.org", "oecd.org", "nasa.gov", "noaa.gov", "nist.gov",
    "canada.ca", "asc-csa.gc.ca", "esa.int", "ec.europa.eu", "europa.eu", "sec.gov", "bls.gov",
    "census.gov", "ons.gov.uk", "wmo.int", "ipcc.ch", "iau.org", "ctbuh.org", "unfpa.org", "cdc.gov",
    "nih.gov", "data.gov.in", "censusindia.gov.in",
)
PUBLISHERS = ("reuters.com", "apnews.com", "bbc.com", "ft.com", "nature.com", "science.org")
REFERENCE = ("wikipedia.org", "britannica.com", "worldometers.info", "nationalgeographic.com",
             "ourworldindata.org", "encyclopedia.com")
USER_GENERATED = (
    "brainly.com", "quora.com", "reddit.com", "facebook.com", "instagram.com", "youtube.com", "youtu.be",
    "tiktok.com", "x.com", "twitter.com", "pinterest.com", "medium.com", "answers.com", "answers.yahoo.com", "chegg.com",
    "coursehero.com", "linkedin.com", "stackexchange.com", "tumblr.com",
)


def _matches(domain, items):
    return any(domain == item or domain.endswith("." + item) for item in items)


def source_type(url):
    domain = urlparse(url).netloc.lower().removeprefix("www.")

    if domain.endswith((".gov", ".gov.uk", ".gov.in", ".gc.ca")):
        return "Government"
    if domain.endswith((".edu", ".ac.uk", ".edu.au")):
        return "Academic"
    if _matches(domain, AUTHORITY_DOMAINS):
        return "Official / institutional"
    if _matches(domain, PUBLISHERS):
        return "Established publisher"
    if _matches(domain, USER_GENERATED):
        return "User-generated"
    if _matches(domain, REFERENCE):
        return "Reference / secondary"
    return "Other \u2014 review source"


# ============================================================
# TAVILY WEB SEARCH
# ============================================================

def tavily_search(query, key, max_results=3, include_domains=None):

    if not key:

        raise ProviderError(
            "Tavily",
            "Tavily API key is missing."
        )

    payload = {
        "api_key": key,
        "query": query[:350],
        "search_depth": "basic",
        "topic": "general",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = list(include_domains)

    try:

        response = _post(
            TAVILY_URL,
            json=payload,
            timeout=(10, 45)
        )

    except requests.RequestException as e:

        raise ProviderError(
            "Tavily",
            f"Network error: {e}"
        ) from e

    if response.status_code in (401, 403):

        raise ProviderError(
            "Tavily",
            "Tavily API key rejected.",
            response.status_code
        )

    if response.status_code == 429:

        raise ProviderError(
            "Tavily",
            "Tavily rate limit or credit limit reached.",
            429
        )

    if response.status_code >= 400:

        raise ProviderError(
            "Tavily",
            f"Tavily API returned HTTP {response.status_code}.",
            response.status_code
        )

    try:

        response_data = response.json()

    except ValueError as e:

        raise ProviderError(
            "Tavily",
            "Invalid JSON response from Tavily."
        ) from e

    if not isinstance(response_data, dict) or not isinstance(response_data.get("results", []), list):
        raise ProviderError("Tavily", "Invalid response structure from Tavily.")

    results = []

    for item in response_data.get("results", []):

        if not isinstance(item, dict):
            continue

        url = item.get("url", "")

        if not isinstance(url, str) or urlparse(url).scheme.lower() not in {"http", "https"} or not urlparse(url).netloc:
            continue

        title = str(item.get("title") or "")
        content = str(item.get("content") or "")

        results.append({

            "title": (
                title[:160]
            ),

            "url": url,

            "domain": (
                urlparse(url).netloc.lower()
            ),

            "source_type": source_type(url),

            "snippet": (
                content
            )[:500],

            # v1.4.1: a larger private text pool from which gather_evidence() picks the sentences that are
            # relevant to the claim. It is removed again before anything is shown or saved.
            "_pool": (
                content
            )[:1500],

            # Tavily returns a publish date for some results; keep it so
            # the reviewer (and the model) can judge how current a source is.
            "published_date": str(item.get("published_date") or ""),
            "relevance_score": item.get("score") if isinstance(item.get("score"), (int, float)) else None,

        })

    return results
