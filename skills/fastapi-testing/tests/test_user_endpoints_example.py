"""Reference integration tests for a CRUD endpoint.

Demonstrates:
  - status code coverage (201, 200, 400, 401, 404, 409, 422)
  - FE-friendly envelope assertion (`success`, `code`, `message`, `data`, `errors`)
  - pagination boundaries
  - PATCH semantics with `exclude_unset`

These are reference tests — adapt paths and schemas to your project.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def assert_envelope(body: dict, *, success: bool, code: int) -> None:
    assert body["success"] is success
    assert body["code"] == code
    assert "message" in body
    assert "data" in body
    assert "errors" in body


# ---- Create ----------------------------------------------------------------

async def test_create_user_returns_201(auth_client: AsyncClient):
    res = await auth_client.post("/v1/users", json={"email": "a@b.com", "name": "Ada"})
    assert res.status_code == 201
    body = res.json()
    assert_envelope(body, success=True, code=201)
    assert body["data"]["email"] == "a@b.com"
    assert body["data"]["id"] > 0


async def test_create_user_duplicate_email_409(auth_client: AsyncClient):
    payload = {"email": "dup@b.com", "name": "First"}
    await auth_client.post("/v1/users", json=payload)
    res = await auth_client.post("/v1/users", json={"email": "dup@b.com", "name": "Second"})
    assert res.status_code == 409
    assert_envelope(res.json(), success=False, code=409)


async def test_create_user_validation_422(auth_client: AsyncClient):
    res = await auth_client.post("/v1/users", json={"email": "not-an-email", "name": ""})
    assert res.status_code == 422
    body = res.json()
    assert_envelope(body, success=False, code=422)
    assert body["errors"]
    field_names = {e["field"] for e in body["errors"]}
    assert "email" in field_names


async def test_create_user_unauthenticated_401(client: AsyncClient):
    res = await client.post("/v1/users", json={"email": "x@y.com", "name": "X"})
    assert res.status_code == 401


# ---- Read ------------------------------------------------------------------

async def test_get_user_404(auth_client: AsyncClient):
    res = await auth_client.get("/v1/users/9999999")
    assert res.status_code == 404
    assert_envelope(res.json(), success=False, code=404)


async def test_list_users_pagination(auth_client: AsyncClient):
    for i in range(25):
        await auth_client.post("/v1/users", json={"email": f"u{i}@x.com", "name": f"U{i}"})

    res = await auth_client.get("/v1/users", params={"page": 1, "size": 10})
    body = res.json()
    assert res.status_code == 200
    assert len(body["data"]["items"]) == 10
    p = body["data"]["pagination"]
    assert p["page"] == 1 and p["size"] == 10
    assert p["has_next"] is True
    assert p["total"] >= 25

    res = await auth_client.get("/v1/users", params={"page": 3, "size": 10})
    p = res.json()["data"]["pagination"]
    assert p["has_next"] is False
    assert len(res.json()["data"]["items"]) <= 10


async def test_list_users_size_capped(auth_client: AsyncClient):
    res = await auth_client.get("/v1/users", params={"size": 9999})
    assert res.status_code == 422  # caller should cap at 100


# ---- Update (PATCH) --------------------------------------------------------

async def test_patch_user_only_touches_sent_fields(auth_client: AsyncClient):
    create = await auth_client.post("/v1/users", json={"email": "p@x.com", "name": "Pat"})
    uid = create.json()["data"]["id"]

    res = await auth_client.patch(f"/v1/users/{uid}", json={"name": "Patrick"})
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["name"] == "Patrick"
    assert body["email"] == "p@x.com"  # unchanged


# ---- Delete ----------------------------------------------------------------

async def test_delete_user_then_get_404(auth_client: AsyncClient):
    create = await auth_client.post("/v1/users", json={"email": "d@x.com", "name": "Del"})
    uid = create.json()["data"]["id"]

    res = await auth_client.delete(f"/v1/users/{uid}")
    assert res.status_code == 204

    res = await auth_client.get(f"/v1/users/{uid}")
    assert res.status_code == 404


# ---- Contract --------------------------------------------------------------

async def test_response_includes_request_id_header(auth_client: AsyncClient):
    res = await auth_client.get("/v1/users", params={"page": 1, "size": 1})
    assert res.headers.get("x-request-id")
