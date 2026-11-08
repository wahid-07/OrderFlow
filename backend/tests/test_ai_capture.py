"""Tests for OrderFlow Phase 3A: Live Catalogue, SKU Alias Engine & Security."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_capture
from app.auth import get_current_user
from app.main import app
from app.models import Order, Product, Retailer, SkuAlias, User

client = TestClient(app)


def authenticate_user(seeded_database, auth_subject: str) -> User:
    """Helper to authenticate test requests as a specific user."""
    with Session(seeded_database) as session:
        user = session.scalar(select(User).where(User.auth_subject == auth_subject))
        assert user is not None, f"Missing test user: {auth_subject}"
        session.expunge(user)

    app.dependency_overrides[get_current_user] = lambda: user
    return user


def clear_auth() -> None:
    app.dependency_overrides.pop(get_current_user, None)


# =====================================================================
# 1. Security & Authentication Tests
# =====================================================================


def test_ai_capture_requires_authentication(seeded_database) -> None:
    """Unauthenticated requests must be rejected with 401."""
    clear_auth()
    response = client.post(
        "/ai/order-captures",
        json={"raw_text": "5 peti biscuit"},
    )
    assert response.status_code == 401


def test_alias_management_requires_authentication(seeded_database) -> None:
    """Listing, creating, or confirming aliases requires authentication."""
    clear_auth()
    assert client.get("/ai/aliases").status_code == 401
    assert (
        client.post(
            "/ai/aliases",
            json={"alias": "test", "canonical_sku": "SKU-BS-075"},
        ).status_code
        == 401
    )
    assert (
        client.patch(
            f"/ai/aliases/{uuid4()}/confirm",
        ).status_code
        == 401
    )


# =====================================================================
# 2. Live Catalogue & Anti-Hallucination Tests
# =====================================================================


def test_ai_capture_matches_live_catalogue(seeded_database, monkeypatch) -> None:
    """AI order capture must resolve items against active products in PostgreSQL."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        response = client.post(
            "/ai/order-captures",
            json={
                "raw_text": (
                    "bhaiya 5 peti biscuit chhota, 2 peti washing powder 1 kilo, "
                    "chai patti 250 wala 1 peti"
                )
            },
        )
        assert response.status_code == 200
        result = response.json()

        # Human review enforcement
        assert result["review_required"] is True
        assert result["order_placed"] is False

        # Live SKUs verified
        lines = result["lines"]
        assert len(lines) == 3
        assert lines[0]["matched_sku"] == "SKU-BS-075"
        assert lines[0]["matched_name"] == "Glucose biscuit"
        assert lines[0]["quantity"] == "5"
        assert lines[0]["unit"] == "case"

        assert lines[1]["matched_sku"] == "SKU-DP-1KG"
        assert lines[1]["matched_name"] == "Detergent powder"
        assert lines[1]["quantity"] == "2"

        assert lines[2]["matched_sku"] == "SKU-TL-250"
        assert lines[2]["matched_name"] == "Tea leaf"
        assert lines[2]["quantity"] == "1"
    finally:
        clear_auth()


def test_ai_capture_ignores_inactive_catalogue_products(
    seeded_database, monkeypatch
) -> None:
    """Inactive products in the database must never be matched by AI capture."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Deactivate SKU-BS-075 in the database
        with Session(seeded_database) as session:
            product = session.scalar(
                select(Product).where(Product.sku == "SKU-BS-075")
            )
            assert product is not None
            product.is_active = False
            session.commit()

        response = client.post(
            "/ai/order-captures",
            json={"raw_text": "5 peti biscuit chhota"},
        )
        assert response.status_code == 200
        result = response.json()
        # Inactive SKU must not be matched
        line = result["lines"][0]
        assert line["matched_sku"] is None
        assert line["needs_clarification"] is True
    finally:
        # Re-activate for other tests
        with Session(seeded_database) as session:
            product = session.scalar(
                select(Product).where(Product.sku == "SKU-BS-075")
            )
            if product:
                product.is_active = True
                session.commit()
        clear_auth()


def test_gemini_anti_hallucination_filters_invented_and_inactive_skus(
    seeded_database, monkeypatch
) -> None:
    """Gemini-proposed SKUs must be discarded if they do not exist as active products."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Mock Gemini output returning an invented SKU and a valid SKU
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini",
            lambda *args, **kwargs: ai_capture.GeminiOrderResult(
                lines=[
                    ai_capture.GeminiOrderLine(
                        line_index=0,
                        quantity=Decimal("10"),
                        candidates=[
                            ai_capture.GeminiCandidate(
                                sku="HALLUCINATED-SKU-999", confidence=0.99
                            ),
                            ai_capture.GeminiCandidate(
                                sku="SKU-DP-1KG", confidence=0.88
                            ),
                        ],
                    )
                ]
            ),
        )

        response = client.post(
            "/ai/order-captures",
            json={"raw_text": "10 peti detergent"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["source"] == "gemini"
        line = result["lines"][0]
        # Anti-hallucination check: HALLUCINATED-SKU-999 filtered out, SKU-DP-1KG selected
        assert line["matched_sku"] == "SKU-DP-1KG"
        assert [c["sku"] for c in line["candidates"]] == ["SKU-DP-1KG"]
    finally:
        clear_auth()


# =====================================================================
# 3. Canonical Detergent SKU & SKU-DT-1KG Alias Verification
# =====================================================================


def test_canonical_detergent_sku_and_alias_resolution(
    seeded_database, monkeypatch
) -> None:
    """Verify SKU-DP-1KG remains canonical and SKU-DT-1KG resolves cleanly to it."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. Verify canonical SKU in DB
    with Session(seeded_database) as session:
        canonical_prod = session.scalar(
            select(Product).where(Product.sku == "SKU-DP-1KG")
        )
        assert canonical_prod is not None
        assert canonical_prod.name == "Detergent powder"

    # 2. Order Desk creates global alias SKU-DT-1KG -> SKU-DP-1KG
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "SKU-DT-1KG",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": True,
            },
        )
        assert alias_resp.status_code == 201
        alias_data = alias_resp.json()
        assert alias_data["alias"] == "SKU-DT-1KG"
        assert alias_data["canonical_sku"] == "SKU-DP-1KG"
        assert alias_data["is_global"] is True
    finally:
        clear_auth()

    # 3. Retailer orders using the client-brief alias SKU-DT-1KG
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        capture_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "4 peti SKU-DT-1KG"},
        )
        assert capture_resp.status_code == 200
        result = capture_resp.json()
        line = result["lines"][0]
        # Must resolve to canonical SKU-DP-1KG via global_alias
        assert line["matched_sku"] == "SKU-DP-1KG"
        assert line["matched_name"] == "Detergent powder"
        assert line["matched_via"] == "global_alias"
        assert line["quantity"] == "4"
        assert line["unit"] == "case"
    finally:
        clear_auth()


# =====================================================================
# 4. Priority Hierarchy & Resolution Order Tests
# =====================================================================


def test_alias_resolution_priority_hierarchy(seeded_database, monkeypatch) -> None:
    """Verify Priority 1 (Retailer alias) > Priority 2 (Global alias) > Priority 3 (AI / Demo)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Setup:
    # Global alias: "special pack" -> SKU-TL-250 (Tea)
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "special pack",
                "canonical_sku": "SKU-TL-250",
                "is_global": True,
            },
        )
        assert resp.status_code == 201
    finally:
        clear_auth()

    # Retailer 1 creates retailer-specific alias: "special pack" -> SKU-DP-1KG (Detergent)
    retailer_1 = authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "special pack",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["retailer_id"] == str(retailer_1.retailer_id)

        # Retailer 1 captures "3 peti special pack"
        # Should match SKU-DP-1KG via retailer_alias (Priority 1 overrides Global Priority 2)
        r1_order = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti special pack"},
        )
        assert r1_order.status_code == 200
        line1 = r1_order.json()["lines"][0]
        assert line1["matched_sku"] == "SKU-DP-1KG"
        assert line1["matched_via"] == "retailer_alias"
    finally:
        clear_auth()

    # Retailer 2 has NO retailer-specific alias for "special pack"
    # Should fall back to Global alias SKU-TL-250 (Priority 2)
    authenticate_user(seeded_database, "second-demo-retailer-user")
    try:
        r2_order = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti special pack"},
        )
        assert r2_order.status_code == 200
        line2 = r2_order.json()["lines"][0]
        assert line2["matched_sku"] == "SKU-TL-250"
        assert line2["matched_via"] == "global_alias"
    finally:
        clear_auth()


# =====================================================================
# 5. Normalization, Conflict Detection & Idempotency
# =====================================================================


def test_alias_normalization_and_conflict_handling(seeded_database) -> None:
    """Aliases must be normalized for case and whitespace, and detect conflicts."""
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # Create alias with messy casing and whitespace
        create_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "  Chai   PATTI  Premium  ",
                "canonical_sku": "SKU-TL-250",
                "is_global": True,
            },
        )
        assert create_resp.status_code == 201

        # Idempotent call: same alias, same canonical product -> returns existing
        duplicate_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "chai patti premium",
                "canonical_sku": "SKU-TL-250",
                "is_global": True,
            },
        )
        assert duplicate_resp.status_code == 201
        assert duplicate_resp.json()["id"] == create_resp.json()["id"]

        # Conflict: same alias mapped to a DIFFERENT product -> 409 Conflict
        conflict_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "chai patti premium",
                "canonical_sku": "SKU-BS-075",
                "is_global": True,
            },
        )
        assert conflict_resp.status_code == 409
        assert "already mapped" in conflict_resp.json()["detail"]
    finally:
        clear_auth()


def test_alias_creation_rejects_invalid_or_inactive_canonical_sku(
    seeded_database,
) -> None:
    """Cannot create an alias mapping to a non-existent or inactive product."""
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        # Non-existent SKU
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "ghost product",
                "canonical_sku": "SKU-NONEXISTENT",
                "is_global": True,
            },
        )
        assert resp.status_code == 404

        # Deactivate SKU-BS-075
        with Session(seeded_database) as session:
            prod = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
            prod.is_active = False
            session.commit()

        # Inactive SKU rejected
        resp_inactive = client.post(
            "/ai/aliases",
            json={
                "alias": "biscuit inactive",
                "canonical_sku": "SKU-BS-075",
                "is_global": True,
            },
        )
        assert resp_inactive.status_code == 404
    finally:
        with Session(seeded_database) as session:
            prod = session.scalar(select(Product).where(Product.sku == "SKU-BS-075"))
            if prod:
                prod.is_active = True
                session.commit()
        clear_auth()


# =====================================================================
# 6. Tenant Isolation & Role Permissions
# =====================================================================


def test_retailer_cannot_create_global_alias(seeded_database) -> None:
    """Retailers are forbidden from creating distributor-wide global aliases."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "global attempt",
                "canonical_sku": "SKU-BS-075",
                "is_global": True,
            },
        )
        assert resp.status_code == 403
        assert "Only Order Desk" in resp.json()["detail"]
    finally:
        clear_auth()


def test_retailer_alias_cross_tenant_isolation(seeded_database, monkeypatch) -> None:
    """Retailer B cannot see or trigger Retailer A's retailer-specific aliases."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. Retailer 1 creates alias: "my custom mix" -> SKU-BS-075
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "my custom mix",
                "canonical_sku": "SKU-BS-075",
                "is_global": False,
            },
        )
        assert resp.status_code == 201

        # Retailer 1 sees it in list
        list_resp = client.get("/ai/aliases")
        assert list_resp.status_code == 200
        aliases = [a["alias"] for a in list_resp.json()]
        assert "my custom mix" in aliases
    finally:
        clear_auth()

    # 2. Retailer 2 inspects aliases
    authenticate_user(seeded_database, "second-demo-retailer-user")
    try:
        list_resp2 = client.get("/ai/aliases")
        assert list_resp2.status_code == 200
        aliases2 = [a["alias"] for a in list_resp2.json()]
        # Retailer 2 MUST NOT see Retailer 1's alias
        assert "my custom mix" not in aliases2

        # Retailer 2 tries to order "5 peti my custom mix"
        order_resp2 = client.post(
            "/ai/order-captures",
            json={"raw_text": "5 peti my custom mix"},
        )
        assert order_resp2.status_code == 200
        line2 = order_resp2.json()["lines"][0]
        # Should NOT match SKU-BS-075 via Retailer 1's alias
        assert line2["matched_via"] != "retailer_alias"
    finally:
        clear_auth()


def test_order_desk_can_confirm_and_promote_alias(seeded_database, monkeypatch) -> None:
    """Order Desk can confirm a retailer-suggested alias and promote it to global."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. Retailer creates alias
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        create_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "fast powder",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert create_resp.status_code == 201
        alias_id = create_resp.json()["id"]
        assert create_resp.json()["confirmed_at"] is None

        # Retailer tries to confirm -> 403 Forbidden
        assert (
            client.patch(f"/ai/aliases/{alias_id}/confirm").status_code == 403
        )
    finally:
        clear_auth()

    # 2. Order Desk confirms and promotes to global
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        confirm_resp = client.patch(
            f"/ai/aliases/{alias_id}/confirm?make_global=true"
        )
        assert confirm_resp.status_code == 200
        confirmed_data = confirm_resp.json()
        assert confirmed_data["confirmed_at"] is not None
        assert confirmed_data["is_global"] is True
        assert confirmed_data["retailer_id"] is None
    finally:
        clear_auth()

    # 3. Now Retailer 2 can also use "fast powder" via the promoted global alias
    authenticate_user(seeded_database, "second-demo-retailer-user")
    try:
        order_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "2 peti fast powder"},
        )
        assert order_resp.status_code == 200
        line = order_resp.json()["lines"][0]
        assert line["matched_sku"] == "SKU-DP-1KG"
        assert line["matched_via"] == "global_alias"
    finally:
        clear_auth()


# =====================================================================
# 7. Phase 3B: Handwritten Photo Order Capture Tests
# =====================================================================

DUMMY_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
DUMMY_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


def test_image_capture_requires_authentication(seeded_database) -> None:
    """Unauthenticated image uploads must return 401."""
    clear_auth()
    response = client.post(
        "/ai/order-captures/image",
        files={"file": ("order.jpg", DUMMY_JPEG, "image/jpeg")},
    )
    assert response.status_code == 401


def test_image_capture_rejects_unauthorized_role(seeded_database) -> None:
    """User with unauthorized role must be rejected with 403."""
    with Session(seeded_database) as session:
        guest = User(
            id=uuid4(),
            auth_subject="guest-user",
            role="guest",
            is_active=True,
        )
        session.add(guest)
        session.commit()
        session.refresh(guest)
        session.expunge(guest)

    app.dependency_overrides[get_current_user] = lambda: guest
    try:
        response = client.post(
            "/ai/order-captures/image",
            files={"file": ("order.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 403
    finally:
        clear_auth()


def test_image_capture_accepts_valid_jpeg_png_webp(
    seeded_database, monkeypatch
) -> None:
    """Valid JPEG, PNG and WebP images must be accepted."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        for filename, content, mime in [
            ("order.jpg", DUMMY_JPEG, "image/jpeg"),
            ("order.png", DUMMY_PNG, "image/png"),
            ("order.webp", DUMMY_WEBP, "image/webp"),
        ]:
            resp = client.post(
                "/ai/order-captures/image",
                files={"file": (filename, content, mime)},
            )
            assert resp.status_code == 200, f"Failed for {mime}: {resp.text}"
            data = resp.json()
            assert data["review_required"] is True
            assert data["order_placed"] is False
            assert len(data["lines"]) > 0
    finally:
        clear_auth()


def test_image_capture_rejects_invalid_file_content_and_empty_file(
    seeded_database,
) -> None:
    """Reject spoofed file headers and empty uploads."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # 1. Plain text disguised as PNG
        spoofed = client.post(
            "/ai/order-captures/image",
            files={"file": ("malicious.png", b"this is plain text not an image", "image/png")},
        )
        assert spoofed.status_code == 415
        assert "Unsupported image format" in spoofed.json()["detail"]

        # 2. Executable disguised as JPG
        exe_file = client.post(
            "/ai/order-captures/image",
            files={"file": ("virus.jpg", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff", "image/jpeg")},
        )
        assert exe_file.status_code == 415

        # 3. Empty file
        empty = client.post(
            "/ai/order-captures/image",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        assert empty.status_code == 400
        assert "empty" in empty.json()["detail"]
    finally:
        clear_auth()


def test_image_capture_rejects_file_exceeding_10mb(seeded_database) -> None:
    """Files exceeding 10 MB must return 413 Payload Too Large."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        oversized_data = b"\xff\xd8\xff\xe0" + b"\x00" * (10 * 1024 * 1024 + 16)
        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("huge.jpg", oversized_data, "image/jpeg")},
        )
        assert resp.status_code == 413
        assert "10 MB limit" in resp.json()["detail"]
    finally:
        clear_auth()


def test_gemini_vision_hindi_handwritten_extraction(
    seeded_database, monkeypatch
) -> None:
    """Gemini Vision extracting Hindi / Devanagari handwritten notes."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-vision-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_vision",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="५ पेटी बिस्कुट",
                        quantity=Decimal("5"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.96)
                        ],
                    ),
                    ai_capture.GeminiVisionOrderLine(
                        line_index=1,
                        original_text="२ पेटी वाशिंग पाउडर",
                        quantity=Decimal("2"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-DP-1KG", confidence=0.93)
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("hindi_note.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["source"] == "gemini"
        assert result["review_required"] is True
        assert result["order_placed"] is False

        lines = result["lines"]
        assert len(lines) == 2

        # Line 1: Devanagari 5 peti biscuit
        assert lines[0]["original_text"] == "५ पेटी बिस्कुट"
        assert lines[0]["quantity"] == "5"
        assert lines[0]["unit"] == "case"
        assert lines[0]["matched_sku"] == "SKU-BS-075"
        assert lines[0]["matched_name"] == "Glucose biscuit"
        assert lines[0]["needs_clarification"] is False

        # Line 2: Devanagari 2 peti washing powder
        assert lines[1]["original_text"] == "२ पेटी वाशिंग पाउडर"
        assert lines[1]["quantity"] == "2"
        assert lines[1]["unit"] == "case"
        assert lines[1]["matched_sku"] == "SKU-DP-1KG"
        assert lines[1]["matched_name"] == "Detergent powder"
    finally:
        clear_auth()


def test_gemini_vision_anti_hallucination_and_unknown_sku_filtering(
    seeded_database, monkeypatch
) -> None:
    """Gemini Vision hallucinated SKUs must be filtered out against live DB."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-vision-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_vision",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="10 peti unknown chips",
                        quantity=Decimal("10"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="FABRICATED-SKU-CHIPS", confidence=0.99),
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.75),
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("note.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        # FABRICATED-SKU-CHIPS must be discarded; only live SKU SKU-BS-075 is kept
        assert line["matched_sku"] == "SKU-BS-075"
        assert [c["sku"] for c in line["candidates"]] == ["SKU-BS-075"]
    finally:
        clear_auth()


def test_image_capture_resolves_aliases_from_handwritten_notes(
    seeded_database, monkeypatch
) -> None:
    """Verify SKU alias engine resolves client brief alias SKU-DT-1KG in handwritten notes."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-vision-key")

    # 1. Create global alias SKU-DT-1KG -> SKU-DP-1KG
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "SKU-DT-1KG",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": True,
            },
        )
        assert alias_resp.status_code == 201
    finally:
        clear_auth()

    # 2. Handwritten note mentions SKU-DT-1KG
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_vision",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="4 peti SKU-DT-1KG",
                        quantity=Decimal("4"),
                        unit="case",
                        candidates=[],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("handwritten.png", DUMMY_PNG, "image/png")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        # Must resolve to canonical SKU-DP-1KG via global_alias
        assert line["matched_sku"] == "SKU-DP-1KG"
        assert line["matched_via"] == "global_alias"
        assert line["quantity"] == "4"
    finally:
        clear_auth()


def test_image_capture_missing_quantity_triggers_clarification(
    seeded_database, monkeypatch
) -> None:
    """Missing or unreadable handwritten quantity prompts clarification question."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-vision-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_vision",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="biscuit peti",
                        quantity=None,  # Quantity could not be determined
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.92)
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("unclear.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        assert line["quantity"] is None
        assert line["needs_clarification"] is True
        assert line["clarification_question"] == 'What quantity should we use for "biscuit peti"?'
    finally:
        clear_auth()


def test_image_capture_gemini_failure_returns_502(
    seeded_database, monkeypatch
) -> None:
    """Gemini Vision API network or upstream failure returns 502 with retry advice."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-vision-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        def raise_vision_error(*args, **kwargs):
            raise RuntimeError("Gemini API connection timeout")

        monkeypatch.setattr(ai_capture, "_generate_with_gemini_vision", raise_vision_error)

        resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("order.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert resp.status_code == 502
        assert "Gemini image parsing is unavailable; retry" in resp.json()["detail"]
    finally:
        clear_auth()


# =====================================================================
# 8. Phase 3C: Hindi Voice Order Capture Tests
# =====================================================================

DUMMY_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00" + b"\x00" * 32
DUMMY_OGG = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 32
DUMMY_WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01" + b"\x00" * 32
DUMMY_M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00isom" + b"\x00" * 32
DUMMY_MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x20" + b"\x00" * 32
DUMMY_MP3_SYNC = b"\xff\xfb\x90\x64\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 32


def test_audio_capture_requires_authentication(seeded_database) -> None:
    """Unauthenticated voice note uploads must return 401."""
    clear_auth()
    response = client.post(
        "/ai/order-captures/audio",
        files={"file": ("voice_order.ogg", DUMMY_OGG, "audio/ogg")},
    )
    assert response.status_code == 401


def test_audio_capture_rejects_unauthorized_role(seeded_database) -> None:
    """User with unauthorized role must be rejected with 403."""
    with Session(seeded_database) as session:
        guest = User(
            id=uuid4(),
            auth_subject="audio-guest-user",
            role="guest",
            is_active=True,
        )
        session.add(guest)
        session.commit()
        session.refresh(guest)
        session.expunge(guest)

    app.dependency_overrides[get_current_user] = lambda: guest
    try:
        response = client.post(
            "/ai/order-captures/audio",
            files={"file": ("voice_order.ogg", DUMMY_OGG, "audio/ogg")},
        )
        assert response.status_code == 403
    finally:
        clear_auth()


def test_audio_capture_accepts_valid_audio_formats(
    seeded_database, monkeypatch
) -> None:
    """Valid OGG, MP3, M4A, WAV, and WebM voice notes must be accepted."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        for filename, content, mime in [
            ("voice.ogg", DUMMY_OGG, "audio/ogg"),
            ("voice.wav", DUMMY_WAV, "audio/wav"),
            ("voice.webm", DUMMY_WEBM, "audio/webm"),
            ("voice.m4a", DUMMY_M4A, "audio/mp4"),
            ("voice_id3.mp3", DUMMY_MP3_ID3, "audio/mpeg"),
            ("voice_sync.mp3", DUMMY_MP3_SYNC, "audio/mpeg"),
        ]:
            resp = client.post(
                "/ai/order-captures/audio",
                files={"file": (filename, content, mime)},
            )
            assert resp.status_code == 200, f"Failed for {mime}: {resp.text}"
            data = resp.json()
            assert data["review_required"] is True
            assert data["order_placed"] is False
            assert len(data["lines"]) > 0
    finally:
        clear_auth()


def test_audio_capture_rejects_invalid_file_content_and_empty_file(
    seeded_database,
) -> None:
    """Reject spoofed audio headers and empty uploads."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # 1. Plain text disguised as MP3
        spoofed = client.post(
            "/ai/order-captures/audio",
            files={"file": ("fake_voice.mp3", b"this is plain text not an audio file", "audio/mpeg")},
        )
        assert spoofed.status_code == 415
        assert "Unsupported audio format" in spoofed.json()["detail"]

        # 2. Executable disguised as OGG
        exe_file = client.post(
            "/ai/order-captures/audio",
            files={"file": ("virus.ogg", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff", "audio/ogg")},
        )
        assert exe_file.status_code == 415

        # 3. Empty file
        empty = client.post(
            "/ai/order-captures/audio",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        assert empty.status_code == 400
        assert "empty" in empty.json()["detail"]
    finally:
        clear_auth()


def test_audio_capture_rejects_file_exceeding_25mb(seeded_database) -> None:
    """Audio files exceeding 25 MB must return 413 Payload Too Large."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        oversized_data = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * (25 * 1024 * 1024 + 16)
        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("huge_recording.wav", oversized_data, "audio/wav")},
        )
        assert resp.status_code == 413
        assert "25 MB limit" in resp.json()["detail"]
    finally:
        clear_auth()


def test_gemini_audio_hindi_hinglish_transcription(
    seeded_database, monkeypatch
) -> None:
    """Gemini Audio transcribing Hindi/Hinglish voice notes with live catalogue resolution."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-audio-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_audio",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="bhaiya 5 peti biscuit chhota bhej dena",
                        quantity=Decimal("5"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.96)
                        ],
                    ),
                    ai_capture.GeminiVisionOrderLine(
                        line_index=1,
                        original_text="aur 2 peti detergent powder 1 kilo",
                        quantity=Decimal("2"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-DP-1KG", confidence=0.94)
                        ],
                    ),
                    ai_capture.GeminiVisionOrderLine(
                        line_index=2,
                        original_text="aur chai patti 250 gram ek peti",
                        quantity=Decimal("1"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-TL-250", confidence=0.98)
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("whatsapp_voice.ogg", DUMMY_OGG, "audio/ogg")},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["source"] == "gemini"
        assert result["review_required"] is True
        assert result["order_placed"] is False

        lines = result["lines"]
        assert len(lines) == 3

        # Line 1: 5 peti biscuit
        assert lines[0]["original_text"] == "bhaiya 5 peti biscuit chhota bhej dena"
        assert lines[0]["quantity"] == "5"
        assert lines[0]["unit"] == "case"
        assert lines[0]["matched_sku"] == "SKU-BS-075"
        assert lines[0]["matched_name"] == "Glucose biscuit"

        # Line 2: 2 peti detergent
        assert lines[1]["original_text"] == "aur 2 peti detergent powder 1 kilo"
        assert lines[1]["quantity"] == "2"
        assert lines[1]["unit"] == "case"
        assert lines[1]["matched_sku"] == "SKU-DP-1KG"
        assert lines[1]["matched_name"] == "Detergent powder"

        # Line 3: 1 peti tea leaf
        assert lines[2]["original_text"] == "aur chai patti 250 gram ek peti"
        assert lines[2]["quantity"] == "1"
        assert lines[2]["unit"] == "case"
        assert lines[2]["matched_sku"] == "SKU-TL-250"
        assert lines[2]["matched_name"] == "Tea leaf"
    finally:
        clear_auth()


def test_gemini_audio_unknown_sku_filtering(
    seeded_database, monkeypatch
) -> None:
    """Anti-hallucination check discards invented SKUs in voice notes."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-audio-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_audio",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="5 peti invented chips",
                        quantity=Decimal("5"),
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="INVENTED-SNACK-999", confidence=0.99),
                            ai_capture.GeminiCandidate(sku="SKU-BS-075", confidence=0.70),
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("recording.webm", DUMMY_WEBM, "audio/webm")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        # INVENTED-SNACK-999 is discarded; SKU-BS-075 is matched
        assert line["matched_sku"] == "SKU-BS-075"
        assert [c["sku"] for c in line["candidates"]] == ["SKU-BS-075"]
    finally:
        clear_auth()


def test_audio_capture_resolves_aliases_from_voice_transcription(
    seeded_database, monkeypatch
) -> None:
    """Voice note mentioning alias SKU-DT-1KG resolves to canonical SKU-DP-1KG."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-audio-key")

    # 1. Create global alias SKU-DT-1KG -> SKU-DP-1KG
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "SKU-DT-1KG",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": True,
            },
        )
        assert alias_resp.status_code == 201
    finally:
        clear_auth()

    # 2. Voice note spoken with SKU-DT-1KG
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_audio",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="bhaiya 3 peti SKU-DT-1KG dal dena",
                        quantity=Decimal("3"),
                        unit="case",
                        candidates=[],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("voice_order.m4a", DUMMY_M4A, "audio/mp4")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        assert line["matched_sku"] == "SKU-DP-1KG"
        assert line["matched_via"] == "global_alias"
        assert line["quantity"] == "3"
    finally:
        clear_auth()


def test_audio_capture_missing_quantity_triggers_clarification(
    seeded_database, monkeypatch
) -> None:
    """Spoken item with missing quantity prompts clarification question."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-audio-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_audio",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="washing powder bhej do",
                        quantity=None,
                        unit="case",
                        candidates=[
                            ai_capture.GeminiCandidate(sku="SKU-DP-1KG", confidence=0.90)
                        ],
                    ),
                ]
            ),
        )

        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("voice.wav", DUMMY_WAV, "audio/wav")},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        assert line["quantity"] is None
        assert line["needs_clarification"] is True
        assert line["clarification_question"] == 'What quantity should we use for "washing powder bhej do"?'
    finally:
        clear_auth()


def test_audio_capture_gemini_failure_returns_502(
    seeded_database, monkeypatch
) -> None:
    """Gemini Audio API network or upstream failure returns 502 with retry advice."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-audio-key")
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        def raise_audio_error(*args, **kwargs):
            raise RuntimeError("Gemini Audio connection error")

        monkeypatch.setattr(ai_capture, "_generate_with_gemini_audio", raise_audio_error)

        resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("voice.ogg", DUMMY_OGG, "audio/ogg")},
        )
        assert resp.status_code == 502
        assert "Gemini audio parsing is unavailable; retry" in resp.json()["detail"]
    finally:
        clear_auth()


# =====================================================================
# 11. Phase 3D: Human Correction & SKU Alias Learning Tests
# =====================================================================


def test_alias_created_upon_sku_correction_with_user_consent(
    seeded_database, monkeypatch
) -> None:
    """When a user corrects an AI-matched SKU and gives consent, save as alias."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    retailer_user = authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # 1. Retailer captures an unrecognized phrase
        resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "2 peti nirma washing powder"},
        )
        assert resp.status_code == 200
        line = resp.json()["lines"][0]
        assert line["quantity"] == "2"

        # 2. User explicitly saves correction as alias with consent
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "nirma washing powder",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert alias_resp.status_code == 201
        alias_data = alias_resp.json()
        assert alias_data["canonical_sku"] == "SKU-DP-1KG"
        assert alias_data["retailer_id"] == str(retailer_user.retailer_id)
        assert alias_data["is_global"] is False

        # 3. Subsequent capture containing this phrase resolves via retailer_alias
        followup_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "5 peti nirma washing powder"},
        )
        assert followup_resp.status_code == 200
        followup_line = followup_resp.json()["lines"][0]
        assert followup_line["matched_sku"] == "SKU-DP-1KG"
        assert followup_line["matched_via"] == "retailer_alias"
        assert followup_line["quantity"] == "5"
    finally:
        clear_auth()


def test_declining_alias_saving_updates_order_line_without_creating_alias(
    seeded_database, monkeypatch
) -> None:
    """If user declines to save alias, no SkuAlias record is created."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Capture raw order
        resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti desi soap powder"},
        )
        assert resp.status_code == 200

        # User chooses NOT to create alias (no POST /ai/aliases call)

        # Verify DB has no alias for "desi soap powder"
        with Session(seeded_database) as session:
            alias = session.scalar(
                select(SkuAlias).where(SkuAlias.alias == "desi soap powder")
            )
            assert alias is None

        # Subsequent capture still does not match via alias
        followup_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti desi soap powder"},
        )
        assert followup_resp.status_code == 200
        assert followup_resp.json()["lines"][0]["matched_via"] != "retailer_alias"
    finally:
        clear_auth()


def test_duplicate_alias_saving_is_idempotent(seeded_database) -> None:
    """Saving an identical alias repeatedly is idempotent and returns 201 with existing record."""
    retailer_user = authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # First save
        first_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "nirma 1kg packet",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert first_resp.status_code == 201
        first_id = first_resp.json()["id"]

        # Duplicate save with different casing/spacing
        dup_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "  NIRMA   1KG  PACKET  ",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert dup_resp.status_code == 201
        assert dup_resp.json()["id"] == first_id

        # Verify DB has only one row
        with Session(seeded_database) as session:
            count = len(
                session.scalars(
                    select(SkuAlias).where(
                        SkuAlias.retailer_id == retailer_user.retailer_id
                    )
                ).all()
            )
            assert count == 1
    finally:
        clear_auth()


def test_conflicting_alias_saving_returns_409(seeded_database) -> None:
    """Attempting to map an existing alias phrase to a different SKU raises 409 Conflict."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Create initial alias
        r1 = client.post(
            "/ai/aliases",
            json={
                "alias": "blue detergent",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert r1.status_code == 201

        # Attempt to map same phrase to biscuit SKU
        conflict = client.post(
            "/ai/aliases",
            json={
                "alias": "blue detergent",
                "canonical_sku": "SKU-BS-075",
                "is_global": False,
            },
        )
        assert conflict.status_code == 409
        detail = conflict.json()["detail"]
        assert "already mapped" in detail
        assert "SKU-DP-1KG" in detail
    finally:
        clear_auth()


def test_saving_alias_for_invalid_or_inactive_sku_fails_404(
    seeded_database,
) -> None:
    """Alias cannot be saved against non-existent or inactive products."""
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # 1. Non-existent SKU
        bad_sku = client.post(
            "/ai/aliases",
            json={
                "alias": "fake product",
                "canonical_sku": "NON-EXISTENT-SKU",
                "is_global": False,
            },
        )
        assert bad_sku.status_code == 404
        assert "Active canonical product" in bad_sku.json()["detail"]

        # 2. Inactive product
        with Session(seeded_database) as session:
            tea = session.scalar(select(Product).where(Product.sku == "SKU-TL-250"))
            assert tea is not None
            tea.is_active = False
            session.commit()

        inactive_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "deactivated tea",
                "canonical_sku": "SKU-TL-250",
                "is_global": False,
            },
        )
        assert inactive_resp.status_code == 404
        assert "Active canonical product" in inactive_resp.json()["detail"]
    finally:
        clear_auth()


def test_retailer_correction_alias_isolation(
    seeded_database, monkeypatch
) -> None:
    """Retailer A's correction alias is strictly isolated and never leaks to Retailer B."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. Retailer A creates alias "daily biscuit" -> SKU-BS-075
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        resp = client.post(
            "/ai/aliases",
            json={
                "alias": "daily biscuit",
                "canonical_sku": "SKU-BS-075",
                "is_global": False,
            },
        )
        assert resp.status_code == 201
    finally:
        clear_auth()

    # 2. Retailer B captures "3 peti daily biscuit"
    authenticate_user(seeded_database, "second-demo-retailer-user")
    try:
        r2_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti daily biscuit"},
        )
        assert r2_resp.status_code == 200
        # Must NOT match via retailer_alias belonging to Retailer A
        line = r2_resp.json()["lines"][0]
        assert line["matched_via"] != "retailer_alias"

        # Retailer B can map "daily biscuit" to a different SKU without conflict
        r2_alias = client.post(
            "/ai/aliases",
            json={
                "alias": "daily biscuit",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert r2_alias.status_code == 201
        assert r2_alias.json()["canonical_sku"] == "SKU-DP-1KG"
    finally:
        clear_auth()


def test_order_desk_can_save_global_correction_alias(
    seeded_database, monkeypatch
) -> None:
    """Order Desk can create global aliases that apply to all retailers; retailers cannot."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # 1. Retailer cannot create global alias
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        forbidden = client.post(
            "/ai/aliases",
            json={
                "alias": "universal tea",
                "canonical_sku": "SKU-TL-250",
                "is_global": True,
            },
        )
        assert forbidden.status_code == 403
    finally:
        clear_auth()

    # 2. Order Desk creates global alias
    authenticate_user(seeded_database, "demo-order-desk-user")
    try:
        created = client.post(
            "/ai/aliases",
            json={
                "alias": "universal tea",
                "canonical_sku": "SKU-TL-250",
                "is_global": True,
            },
        )
        assert created.status_code == 201
        assert created.json()["is_global"] is True
    finally:
        clear_auth()

    # 3. Both Retailer A and Retailer B resolve via global_alias
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        ra_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "2 peti universal tea"},
        )
        assert ra_resp.status_code == 200
        assert ra_resp.json()["lines"][0]["matched_via"] == "global_alias"
        assert ra_resp.json()["lines"][0]["matched_sku"] == "SKU-TL-250"
    finally:
        clear_auth()

    authenticate_user(seeded_database, "second-demo-retailer-user")
    try:
        rb_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "4 peti universal tea"},
        )
        assert rb_resp.status_code == 200
        assert rb_resp.json()["lines"][0]["matched_via"] == "global_alias"
        assert rb_resp.json()["lines"][0]["matched_sku"] == "SKU-TL-250"
    finally:
        clear_auth()


def test_correction_consistency_across_text_photo_and_voice(
    seeded_database, monkeypatch
) -> None:
    """An alias learned from human correction works identically across text, photo, and voice."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Create alias
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "special desi detergent",
                "canonical_sku": "SKU-DP-1KG",
                "is_global": False,
            },
        )
        assert alias_resp.status_code == 201

        # 1. Text capture
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini",
            lambda *args, **kwargs: ai_capture.GeminiOrderResult(
                lines=[
                    ai_capture.GeminiOrderLine(
                        line_index=0,
                        quantity=Decimal("3"),
                        candidates=[],
                    )
                ]
            ),
        )
        text_resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "3 peti special desi detergent"},
        )
        assert text_resp.status_code == 200
        assert text_resp.json()["lines"][0]["matched_sku"] == "SKU-DP-1KG"
        assert text_resp.json()["lines"][0]["matched_via"] == "retailer_alias"

        # 2. Photo capture
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_vision",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="3 peti special desi detergent",
                        quantity=Decimal("3"),
                        unit="case",
                        candidates=[],
                    )
                ]
            ),
        )
        photo_resp = client.post(
            "/ai/order-captures/image",
            files={"file": ("photo.jpg", DUMMY_JPEG, "image/jpeg")},
        )
        assert photo_resp.status_code == 200
        assert photo_resp.json()["lines"][0]["matched_sku"] == "SKU-DP-1KG"
        assert photo_resp.json()["lines"][0]["matched_via"] == "retailer_alias"

        # 3. Voice capture
        monkeypatch.setattr(
            ai_capture,
            "_generate_with_gemini_audio",
            lambda *args, **kwargs: ai_capture.GeminiVisionOrderResult(
                lines=[
                    ai_capture.GeminiVisionOrderLine(
                        line_index=0,
                        original_text="bhaiya 3 peti special desi detergent bhejo",
                        quantity=Decimal("3"),
                        unit="case",
                        candidates=[],
                    )
                ]
            ),
        )
        voice_resp = client.post(
            "/ai/order-captures/audio",
            files={"file": ("voice.m4a", DUMMY_M4A, "audio/mp4")},
        )
        assert voice_resp.status_code == 200
        assert voice_resp.json()["lines"][0]["matched_sku"] == "SKU-DP-1KG"
        assert voice_resp.json()["lines"][0]["matched_via"] == "retailer_alias"
    finally:
        clear_auth()


def test_confirming_corrected_line_does_not_place_order(
    seeded_database, monkeypatch
) -> None:
    """AI order capture and alias learning never automatically places orders into the database."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    authenticate_user(seeded_database, "demo-retailer-user")
    try:
        # Submit AI capture
        resp = client.post(
            "/ai/order-captures",
            json={"raw_text": "5 peti biscuit, 2 peti washing powder"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review_required"] is True
        assert data["order_placed"] is False

        # Save an alias correction
        alias_resp = client.post(
            "/ai/aliases",
            json={
                "alias": "parle g",
                "canonical_sku": "SKU-BS-075",
                "is_global": False,
            },
        )
        assert alias_resp.status_code == 201

        # Verify no orders placed in the database
        with Session(seeded_database) as session:
            orders_count = len(session.scalars(select(Order)).all())
            assert orders_count == 0
    finally:
        clear_auth()




