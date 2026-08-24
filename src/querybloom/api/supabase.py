from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import requests
from dotenv import load_dotenv
from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    anon_key: str

    @property
    def configured(self) -> bool:
        return bool(self.url and self.anon_key)

    @property
    def auth_url(self) -> str:
        return f"{self.url}/auth/v1"

    @property
    def rest_url(self) -> str:
        return f"{self.url}/rest/v1"


@dataclass(frozen=True)
class SupabaseUser:
    id: str
    email: str | None
    access_token: str
    raw: dict[str, Any]


def _settings_from_env() -> SupabaseSettings:
    # Load .env by traversing parent directories to workspace/project root
    for p in Path(__file__).resolve().parents:
        env_file = p / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file)
            break
    else:
        load_dotenv()

    return SupabaseSettings(
        url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
        anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
    )


def _supabase_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in .env.",
    )


def _parse_response(response: requests.Response) -> Any:
    if response.status_code == status.HTTP_204_NO_CONTENT:
        return {}
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text


def _raise_for_supabase_error(response: requests.Response) -> None:
    if response.status_code < 400:
        return

    detail = _parse_response(response)
    raise HTTPException(status_code=response.status_code, detail=detail)


class SupabaseClient:
    def __init__(self, settings: SupabaseSettings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.configured

    def _ensure_configured(self) -> None:
        if not self.configured:
            raise _supabase_unavailable()

    def _headers(self, access_token: str | None = None, prefer: str | None = None) -> dict[str, str]:
        self._ensure_configured()
        headers = {
            "apikey": self.settings.anon_key,
            "Authorization": f"Bearer {access_token or self.settings.anon_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: str | None = None,
        prefer: str | None = None,
        params: dict[str, Any] | None = None,
        payload: Any | None = None,
        timeout: int = 30,
    ) -> Any:
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(access_token=access_token, prefer=prefer),
                params=params,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to reach Supabase server ({self.settings.url}): {exc}. Please verify your SUPABASE_URL and internet connection.",
            ) from exc
        _raise_for_supabase_error(response)
        return _parse_response(response)

    def auth_signup(self, email: str, password: str, display_name: str | None = None) -> Any:
        data: dict[str, Any] = {}
        if display_name:
            data["display_name"] = display_name
        return self._request(
            "POST",
            f"{self.settings.auth_url}/signup",
            payload={"email": email, "password": password, "data": data},
        )

    def auth_login(self, email: str, password: str) -> Any:
        return self._request(
            "POST",
            f"{self.settings.auth_url}/token",
            params={"grant_type": "password"},
            payload={"email": email, "password": password},
        )

    def auth_logout(self, access_token: str) -> Any:
        return self._request(
            "POST",
            f"{self.settings.auth_url}/logout",
            access_token=access_token,
        )

    def get_user(self, access_token: str) -> SupabaseUser:
        payload = self._request(
            "GET",
            f"{self.settings.auth_url}/user",
            access_token=access_token,
        )
        user_id = payload.get("id") if isinstance(payload, dict) else None
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Supabase user response")
        return SupabaseUser(
            id=user_id,
            email=payload.get("email"),
            access_token=access_token,
            raw=payload,
        )

    def rest_select(self, access_token: str, table: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"{self.settings.rest_url}/{table}",
            access_token=access_token,
            params=params,
        )
        return payload if isinstance(payload, list) else []

    def rest_insert(self, access_token: str, table: str, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"{self.settings.rest_url}/{table}",
            access_token=access_token,
            prefer="return=representation",
            payload=payload,
        )
        return response if isinstance(response, list) else []

    def rest_update(self, access_token: str, table: str, params: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request(
            "PATCH",
            f"{self.settings.rest_url}/{table}",
            access_token=access_token,
            prefer="return=representation",
            params=params,
            payload=payload,
        )
        return response if isinstance(response, list) else []

    def rest_delete(self, access_token: str, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._request(
            "DELETE",
            f"{self.settings.rest_url}/{table}",
            access_token=access_token,
            prefer="return=representation",
            params=params,
        )
        return response if isinstance(response, list) else []


def get_supabase_client(*, required: bool = True) -> SupabaseClient:
    client = SupabaseClient(_settings_from_env())
    if required and not client.configured:
        raise _supabase_unavailable()
    return client


def bearer_token_from_header(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expected Authorization: Bearer <token>")
    return token.strip()


def require_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SupabaseUser:
    client = get_supabase_client(required=True)
    token = bearer_token_from_header(authorization)
    return client.get_user(token)
