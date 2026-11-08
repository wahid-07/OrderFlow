"""Supabase Auth Admin provisioning and compensation service.

Used by distributor order desk and admin workflows to provision salesman accounts.
Never exposes the service-role key to client browsers or API responses.
"""

import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import HTTPException, status

from app.config import get_supabase_service_role_key, get_supabase_url

logger = logging.getLogger(__name__)


def get_supabase_admin_config() -> tuple[str | None, str | None]:
    """Retrieve Supabase URL and service role key securely from environment."""
    supabase_url = get_supabase_url()
    service_role_key = get_supabase_service_role_key()
    return supabase_url, service_role_key


def is_supabase_admin_configured() -> bool:
    url, key = get_supabase_admin_config()
    return bool(url and key)


def is_test_environment() -> bool:
    """Check if execution is running in automated tests or explicit mock development mode."""
    return bool(
        os.getenv("ALLOW_MOCK_AUTH", "").lower() in ("true", "1")
        or os.getenv("PYTEST_CURRENT_TEST")
        or os.getenv("TESTING", "").lower() in ("true", "1")
    )


def provision_supabase_salesman(
    email: str | None,
    display_name: str,
    phone: str | None = None,
    password: str | None = None,
    auth_subject: str | None = None,
) -> tuple[str, bool, str | None]:
    """Provision a salesman in Supabase Auth Admin API if configured, or fail safely.

    Returns:
        tuple[str, bool, str | None]: (auth_subject, created_remotely, invitation_link)
    """
    supabase_url, service_role_key = get_supabase_admin_config()

    # If auth_subject is explicitly provided (e.g. pre-existing Supabase user or test fixture)
    if auth_subject and auth_subject.strip():
        return auth_subject.strip(), False, None

    # Production safety guard: If Supabase admin credentials are missing
    if not (supabase_url and service_role_key):
        if is_test_environment():
            # Strictly allowed only in unit/integration test suites
            mock_id = f"test-salesman-sub-{uuid.uuid4()}"
            mock_invite = f"http://localhost:5173/auth/setup-password?token=mock-{uuid.uuid4().hex[:12]}&type=invite"
            return mock_id, False, mock_invite

        # In production / staging without credentials, fail safely
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Supabase Admin API credentials (SUPABASE_SERVICE_ROLE_KEY / SUPABASE_URL) "
                "are not configured. Cannot provision salesman authentication safely."
            ),
        )

    if not email or not email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required to provision a Supabase salesman user account",
        )

    clean_email = email.strip().lower()

    # Flow A: Invitation workflow (preferred FMCG salesman onboarding)
    if not password:
        # Generate invite link: creates user with email_confirmed_at=None and provides action_link
        admin_endpoint = f"{supabase_url}/auth/v1/admin/generate_link"
        payload: dict[str, Any] = {
            "type": "invite",
            "email": clean_email,
            "data": {
                "role": "salesman",
                "display_name": display_name.strip(),
                "phone": phone.strip() if phone else None,
            },
        }

        req = urllib.request.Request(
            admin_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
                remote_sub = body.get("user", {}).get("id") or body.get("id")
                action_link = body.get("properties", {}).get("action_link")
                if not remote_sub:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Supabase Auth did not return a valid user ID for invitation",
                    )
                return str(remote_sub), True, action_link

        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="ignore")
            logger.error("Supabase Admin API error (%d): %s", error.code, error_body)

            if error.code == 422 or "already registered" in error_body.lower() or "unique" in error_body.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email '{clean_email}' is already registered in Supabase Auth",
                ) from error

            # If generate_link is not supported (404), fall back to /auth/v1/invite
            if error.code == 404:
                invite_endpoint = f"{supabase_url}/auth/v1/invite"
                invite_req = urllib.request.Request(
                    invite_endpoint,
                    data=json.dumps({
                        "email": clean_email,
                        "data": {
                            "role": "salesman",
                            "display_name": display_name.strip(),
                            "phone": phone.strip() if phone else None,
                        },
                    }).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "apikey": service_role_key,
                        "Authorization": f"Bearer {service_role_key}",
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(invite_req, timeout=10) as inv_res:
                        inv_body = json.loads(inv_res.read().decode("utf-8"))
                        inv_sub = inv_body.get("id")
                        if not inv_sub:
                            raise HTTPException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Supabase Auth invite did not return user ID",
                            )
                        return str(inv_sub), True, None
                except Exception as fallback_err:
                    logger.error("Fallback invite failed: %s", fallback_err)

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase Auth provisioning failed with status {error.code}",
            ) from error

        except urllib.error.URLError as error:
            logger.error("Network error reaching Supabase Admin API: %s", error)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Supabase Auth Admin service",
            ) from error

    # Flow B: Explicit password setup (e.g. distributor admin manual kiosk/handheld provisioning)
    else:
        admin_endpoint = f"{supabase_url}/auth/v1/admin/users"
        payload = {
            "email": clean_email,
            "password": password,
            # Email is not marked confirmed unless the salesman accesses setup link or verifies
            "email_confirm": False,
            "user_metadata": {
                "role": "salesman",
                "display_name": display_name.strip(),
                "phone": phone.strip() if phone else None,
            },
        }

        req = urllib.request.Request(
            admin_endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
                remote_sub = body.get("id")
                if not remote_sub:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Supabase Auth did not return a valid user ID",
                    )

                action_link: str | None = None
                try:
                    link_req = urllib.request.Request(
                        f"{supabase_url}/auth/v1/admin/generate_link",
                        data=json.dumps({"type": "magiclink", "email": clean_email}).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "apikey": service_role_key,
                            "Authorization": f"Bearer {service_role_key}",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(link_req, timeout=5) as link_res:
                        link_body = json.loads(link_res.read().decode("utf-8"))
                        action_link = link_body.get("properties", {}).get("action_link")
                except Exception:
                    pass

                return str(remote_sub), True, action_link

        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="ignore")
            logger.error("Supabase Admin API error (%d): %s", error.code, error_body)

            if error.code == 422 or "already registered" in error_body.lower() or "unique" in error_body.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with email '{clean_email}' is already registered in Supabase Auth",
                ) from error

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase Auth provisioning failed with status {error.code}",
            ) from error

        except urllib.error.URLError as error:
            logger.error("Network error reaching Supabase Admin API: %s", error)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to reach Supabase Auth Admin service",
            ) from error


def rollback_supabase_salesman(auth_subject: str) -> None:
    """Compensating transaction: Delete the newly created Supabase user if local DB commit fails."""
    supabase_url, service_role_key = get_supabase_admin_config()
    if not (supabase_url and service_role_key and auth_subject):
        return

    admin_endpoint = f"{supabase_url}/auth/v1/admin/users/{auth_subject}"
    req = urllib.request.Request(
        admin_endpoint,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        },
        method="DELETE",
    )

    try:
        with urllib.request.urlopen(req, timeout=8):
            logger.info("Successfully rolled back Supabase Auth user %s", auth_subject)
    except Exception as exc:
        logger.warning("Failed to rollback Supabase Auth user %s: %s", auth_subject, exc)
