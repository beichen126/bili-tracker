from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from bili_tracker.adapters.sources.url_policy import UrlPolicy


class HttpClientError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, msg, headers, fp)


class SafeHttpClient:
    """Small bounded HTTP client with explicit redirect and response checks."""

    def __init__(
        self,
        *,
        policy: UrlPolicy | None = None,
        timeout: float = 10.0,
        max_response_bytes: int = 2_000_000,
        transport: Callable[[str, str, Mapping[str, str], float, int], HttpResponse] | None = None,
    ) -> None:
        self.policy = policy or UrlPolicy()
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self.transport = transport

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> HttpResponse:
        current = url
        request_headers = dict(headers or {})
        for _ in range(self.policy.max_redirects + 1):
            try:
                self.policy.validate(current)
                if self.transport:
                    response = self.transport(
                        "GET", current, request_headers, self.timeout, self.max_response_bytes
                    )
                else:
                    response = self._request(current, request_headers)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    current = self.policy.redirect(current, exc.headers["Location"])
                    continue
                raise HttpClientError(self._status_code(exc.code), "HTTP request failed") from exc
            except urllib.error.URLError as exc:
                raise HttpClientError("source.network_error", "network request failed") from exc
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise HttpClientError("source.redirect_invalid", "redirect has no location")
                current = self.policy.redirect(current, location)
                continue
            if response.status >= 400:
                raise HttpClientError(self._status_code(response.status), "HTTP request failed")
            if len(response.body) > self.max_response_bytes:
                raise HttpClientError(
                    "source.response_too_large", "response exceeds configured limit"
                )
            return response
        raise HttpClientError("source.redirect_limit", "too many redirects")

    def get_json(self, url: str, *, headers: Mapping[str, str] | None = None) -> object:
        response = self.get(url, headers=headers)
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpClientError("source.invalid_json", "response is not valid JSON") from exc

    def _request(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        opener = urllib.request.build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=self.timeout) as response:
            body = response.read(self.max_response_bytes + 1)
            return HttpResponse(response.status, dict(response.headers.items()), body)

    @staticmethod
    def _status_code(status: int) -> str:
        return {
            401: "source.unauthorized",
            403: "source.forbidden",
            404: "source.not_found",
            429: "source.rate_limited",
        }.get(status, "source.remote_error" if status >= 500 else "source.http_error")
