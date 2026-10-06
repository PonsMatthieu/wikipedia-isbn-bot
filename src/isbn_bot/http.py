import hashlib
import json
import time
from collections.abc import Callable

import requests

from .config import Settings
from .state import State


class HttpError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, kind: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


class Transport:
    """Sessions séparées des comptes wiki. Retente uniquement les lectures HTTP."""
    def __init__(self, settings: Settings, state: State | None = None, session=None, sleep=time.sleep):
        self.settings, self.state = settings, state
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})
        self.sleep, self.last_request = sleep, 0.0

    def request(self, method: str, url: str, *, params=None, data=None, retry: bool = True,
                accepted_statuses: tuple[int, ...] = ()):
        attempts = self.settings.max_retries if retry and method == "GET" else 1
        for attempt in range(attempts):
            delay = self.settings.request_delay - (time.monotonic() - self.last_request)
            if delay > 0:
                self.sleep(delay)
            self.last_request = time.monotonic()
            try:
                response = self.session.request(method, url, params=params, data=data, timeout=self.settings.timeout)
            except requests.RequestException as exc:
                if attempt + 1 == attempts:
                    # Ne pas exposer l'URL : elle peut contenir une clé API.
                    raise HttpError(type(exc).__name__ + " pendant une requête HTTP", kind=type(exc).__name__) from None
                self.sleep(min(2 ** (attempt + 1), 32))
                continue
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                try:
                    retry_after = float(response.headers.get("Retry-After", "0"))
                except ValueError:
                    retry_after = 0
                self.sleep(min(max(retry_after, 2 ** (attempt + 1)), 60))
                continue
            if response.status_code >= 400 and response.status_code not in accepted_statuses:
                raise HttpError(f"HTTP {response.status_code}", status_code=response.status_code)
            return response
        raise HttpError("Nombre maximal de tentatives atteint")

    def json(self, url: str, params: dict | None = None, cache_ttl: int = 86400):
        # Uniquement catalogues publics. Aucune réponse de connexion n'est mise en cache.
        key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        if self.state and cache_ttl:
            row = self.state.db.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
            if row and row["created_at"] > time.time() - cache_ttl:
                return json.loads(row["value"])
        response = self.request("GET", url, params=params)
        try:
            value = response.json()
        except ValueError:
            raise HttpError("Réponse JSON invalide") from None
        if self.state and cache_ttl:
            with self.state.db:
                self.state.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        return value

    def text(self, url: str, params: dict | None = None, cache_ttl: int = 86400, *,
             not_found_validator: Callable[[str], bool] | None = None) -> str:
        # Le 404 n'est acceptable qu'après validation du corps par le catalogue.
        # Isoler ce cache pour ne pas servir un 404 à un appel HTTP ordinaire.
        prefix = "text:validated404:" if not_found_validator else "text:"
        key = hashlib.sha256((prefix + url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        if self.state and cache_ttl:
            row = self.state.db.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
            if row and row["created_at"] > time.time() - cache_ttl:
                return json.loads(row["value"])
        response = self.request("GET", url, params=params,
                                accepted_statuses=(404,) if not_found_validator else ())
        response.encoding = "utf-8"
        value = response.text
        if response.status_code == 404 and (not not_found_validator or not not_found_validator(value)):
            raise HttpError("HTTP 404", status_code=404)
        if self.state and cache_ttl:
            with self.state.db:
                self.state.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        return value
