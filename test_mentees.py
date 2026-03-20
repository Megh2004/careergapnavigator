"""
test_mentees.py
===============
Automated tests for the Mentee CRUD endpoints in backend.py.

Coverage:
  ─ Happy path (each endpoint with valid data)
  ─ Edge cases (missing fields, bad types, out-of-range values, wrong ID format,
                non-existent IDs, inverted progress range, wrong content-type, etc.)

Run with:
    pytest test_mentees.py -v

The tests mock out psycopg2 so no real database connection is needed.
"""

import json
import uuid
from unittest.mock import patch, MagicMock

import pytest
import werkzeug

# Flask's test client expects `werkzeug.__version__`, but some newer Werkzeug
# versions removed that attribute. Patch it for compatibility so tests can run.
if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "unknown"

# ── Import the Flask app without triggering init_db at module level ─────────────
# We patch init_db before importing backend to avoid a real DB call.
with patch("db.get_connection"), patch("db.init_db"):
    from backend import app  # noqa: E402


# ── Shared fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Return a Flask test client with testing mode enabled."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# A hard‑coded UUID used across tests as a known valid ID
KNOWN_ID = str(uuid.uuid4())

# Minimal valid mentee as returned from the DB helper
_SAMPLE_MENTEE = {
    "id": KNOWN_ID,
    "name": "Alice Turing",
    "target": "Data Scientist",
    "category": "Fresher",
    "progress": 30,
    "skills": ["Python", "SQL"],
    "tasks": [{"title": "Complete NumPy module", "done": False}],
    "created_at": "2026-03-20T10:00:00+00:00",
    "updated_at": "2026-03-20T10:00:00+00:00",
}


# ══════════════════════════════════════════════════════════════════════════════
# ── LIST  GET /api/mentees ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestListMentees:

    # ── Happy path ─────────────────────────────────────────────────────────────
    def test_list_returns_all_mentees(self, client):
        """Happy path: GET /api/mentees returns 200 with the list from DB."""
        with patch("backend.db_list_mentees", return_value=[_SAMPLE_MENTEE]) as mock_list:
            resp = client.get("/api/mentees")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["count"] == 1
        assert body["mentees"][0]["name"] == "Alice Turing"
        mock_list.assert_called_once()

    def test_list_empty_db_returns_zero_count(self, client):
        """Happy path: empty table returns count=0 without error."""
        with patch("backend.db_list_mentees", return_value=[]):
            resp = client.get("/api/mentees")
        assert resp.status_code == 200
        assert resp.get_json()["count"] == 0

    def test_list_search_query_forwarded_to_db(self, client):
        """Happy path: 'q' query param is forwarded to db_list_mentees."""
        with patch("backend.db_list_mentees", return_value=[]) as mock_list:
            client.get("/api/mentees?q=Alice")
        mock_list.assert_called_once_with(
            q="Alice", category="",
            min_progress=None, max_progress=None,
            sort_by="name_asc",
        )

    def test_list_category_filter_fresher(self, client):
        """Happy path: category=Fresher is accepted and forwarded."""
        with patch("backend.db_list_mentees", return_value=[_SAMPLE_MENTEE]) as mock_list:
            resp = client.get("/api/mentees?category=Fresher")
        assert resp.status_code == 200
        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["category"] == "Fresher"

    def test_list_sort_progress_desc(self, client):
        """Happy path: sort=progress_desc is a valid option."""
        with patch("backend.db_list_mentees", return_value=[_SAMPLE_MENTEE]):
            resp = client.get("/api/mentees?sort=progress_desc")
        assert resp.status_code == 200

    def test_list_progress_range(self, client):
        """Happy path: min_progress and max_progress are parsed and forwarded."""
        with patch("backend.db_list_mentees", return_value=[_SAMPLE_MENTEE]) as mock_list:
            resp = client.get("/api/mentees?min_progress=10&max_progress=80")
        assert resp.status_code == 200
        assert mock_list.call_args.kwargs["min_progress"] == 10
        assert mock_list.call_args.kwargs["max_progress"] == 80

    # ── Edge cases ─────────────────────────────────────────────────────────────
    def test_list_invalid_category_returns_400(self, client):
        """Edge case: unknown category value is rejected with 400."""
        resp = client.get("/api/mentees?category=Intern")
        assert resp.status_code == 400
        assert "category" in resp.get_json()["error"].lower()

    def test_list_invalid_sort_returns_400(self, client):
        """Edge case: unsupported sort value is rejected."""
        resp = client.get("/api/mentees?sort=random_order")
        assert resp.status_code == 400
        assert "sort" in resp.get_json()["error"].lower()

    def test_list_non_integer_min_progress_returns_400(self, client):
        """Edge case: non-numeric min_progress is rejected."""
        resp = client.get("/api/mentees?min_progress=abc")
        assert resp.status_code == 400

    def test_list_out_of_range_min_progress_returns_400(self, client):
        """Edge case: min_progress > 100 is rejected."""
        resp = client.get("/api/mentees?min_progress=150")
        assert resp.status_code == 400

    def test_list_inverted_range_returns_400(self, client):
        """Edge case: min_progress > max_progress is illogical and rejected."""
        resp = client.get("/api/mentees?min_progress=80&max_progress=20")
        assert resp.status_code == 400
        body = resp.get_json()
        assert "cannot be greater" in body["error"]

    def test_list_db_error_returns_503(self, client):
        """Edge case: DB failure surfaces as 503, not a 500 crash."""
        with patch("backend.db_list_mentees", side_effect=Exception("connection refused")):
            resp = client.get("/api/mentees")
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# ── GET  /api/mentees/<id> ─────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestGetMentee:

    def test_get_existing_mentee_returns_200(self, client):
        """Happy path: fetching a known ID returns the mentee object."""
        with patch("backend.db_get_mentee", return_value=_SAMPLE_MENTEE):
            resp = client.get(f"/api/mentees/{KNOWN_ID}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert body["mentee"]["id"] == KNOWN_ID

    def test_get_nonexistent_mentee_returns_404(self, client):
        """Edge case: valid UUID but not in DB → 404 with a meaningful message."""
        fake_id = str(uuid.uuid4())
        with patch("backend.db_get_mentee", return_value=None):
            resp = client.get(f"/api/mentees/{fake_id}")
        assert resp.status_code == 404
        assert fake_id in resp.get_json()["error"]

    def test_get_invalid_uuid_format_returns_400(self, client):
        """Edge case: garbage ID string → 400 before hitting the DB."""
        resp = client.get("/api/mentees/not-a-real-uuid!!")
        assert resp.status_code == 400
        assert "valid mentee ID" in resp.get_json()["error"]

    def test_get_db_error_returns_503(self, client):
        """Edge case: DB failure → 503."""
        with patch("backend.db_get_mentee", side_effect=Exception("timeout")):
            resp = client.get(f"/api/mentees/{KNOWN_ID}")
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# ── CREATE  POST /api/mentees ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateMentee:

    def _post(self, client, payload):
        return client.post(
            "/api/mentees",
            data=json.dumps(payload),
            content_type="application/json",
        )

    # ── Happy path ─────────────────────────────────────────────────────────────
    def test_create_minimal_valid_mentee(self, client):
        """Happy path: name + target + category is all that's required."""
        payload = {
            "name": "Bob Marley",
            "target": "Backend Engineer",
            "category": "Fresher",
        }
        created = {**_SAMPLE_MENTEE, "name": "Bob Marley",
                   "target": "Backend Engineer", "category": "Fresher", "progress": 0}
        with patch("backend.db_create_mentee", return_value=created):
            resp = self._post(client, payload)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "created"
        assert body["mentee"]["name"] == "Bob Marley"

    def test_create_mentee_with_all_fields(self, client):
        """Happy path: POST with optional fields (skills, tasks, progress)."""
        payload = {
            "name": "Carol Danvers",
            "target": "Cloud Engineer",
            "category": "Switcher",
            "progress": 60,
            "skills": ["AWS", "Docker"],
            "tasks": [{"title": "Write a Terraform module", "done": False}],
        }
        with patch("backend.db_create_mentee", return_value={**_SAMPLE_MENTEE, **payload}):
            resp = self._post(client, payload)
        assert resp.status_code == 201

    def test_create_switcher_category(self, client):
        """Happy path: 'Switcher' is a valid category."""
        payload = {"name": "Dan Brown", "target": "ML Engineer", "category": "Switcher"}
        with patch("backend.db_create_mentee", return_value={**_SAMPLE_MENTEE, **payload}):
            resp = self._post(client, payload)
        assert resp.status_code == 201

    # ── Edge cases ─────────────────────────────────────────────────────────────
    def test_create_missing_name_returns_400(self, client):
        """Edge case: missing 'name' field → 400 with detail."""
        payload = {"target": "QA Engineer", "category": "Fresher"}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        body = resp.get_json()
        assert any("name" in e for e in body["details"])

    def test_create_missing_target_returns_400(self, client):
        """Edge case: missing 'target' field → 400."""
        payload = {"name": "Eve", "category": "Fresher"}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        assert any("target" in e for e in resp.get_json()["details"])

    def test_create_blank_name_returns_400(self, client):
        """Edge case: whitespace-only name → 400."""
        payload = {"name": "   ", "target": "DevOps", "category": "Fresher"}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_name_too_short_returns_400(self, client):
        """Edge case: single-character name → 400."""
        payload = {"name": "X", "target": "DevOps", "category": "Fresher"}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        assert any("2 characters" in e for e in resp.get_json()["details"])

    def test_create_name_too_long_returns_400(self, client):
        """Edge case: name exceeding 120 chars → 400."""
        payload = {"name": "A" * 121, "target": "DevOps", "category": "Fresher"}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_invalid_category_returns_400(self, client):
        """Edge case: 'Intern' is not a valid category → 400 with hint."""
        payload = {"name": "Frank", "target": "DevOps", "category": "Intern"}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        body = resp.get_json()
        assert any("Fresher" in e or "Switcher" in e for e in body["details"])

    def test_create_progress_below_zero_returns_400(self, client):
        """Edge case: progress = -5 → 400."""
        payload = {"name": "Grace", "target": "DevOps", "category": "Fresher", "progress": -5}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_progress_above_100_returns_400(self, client):
        """Edge case: progress = 150 → 400."""
        payload = {"name": "Harry", "target": "DevOps", "category": "Fresher", "progress": 150}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_skills_not_list_returns_400(self, client):
        """Edge case: skills as a string instead of array → 400."""
        payload = {"name": "Iris", "target": "PM", "category": "Fresher", "skills": "Python"}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        assert any("array" in e for e in resp.get_json()["details"])

    def test_create_skills_with_non_string_item_returns_400(self, client):
        """Edge case: skills array contains an integer → 400."""
        payload = {"name": "Iris", "target": "PM", "category": "Fresher", "skills": ["Python", 42]}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_tasks_without_title_returns_400(self, client):
        """Edge case: task object missing 'title' → 400."""
        payload = {
            "name": "Jack",
            "target": "SRE",
            "category": "Switcher",
            "tasks": [{"done": False}],   # no title
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400
        assert any("title" in e for e in resp.get_json()["details"])

    def test_create_task_done_not_bool_returns_400(self, client):
        """Edge case: task 'done' field is a string instead of bool → 400."""
        payload = {
            "name": "Kate",
            "target": "SRE",
            "category": "Switcher",
            "tasks": [{"title": "Deploy app", "done": "yes"}],
        }
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_create_non_json_content_type_returns_415(self, client):
        """Edge case: form data instead of JSON → 415 Unsupported Media Type."""
        resp = client.post(
            "/api/mentees",
            data={"name": "Leo", "target": "DevOps", "category": "Fresher"},
        )
        assert resp.status_code == 415

    def test_create_db_error_returns_503(self, client):
        """Edge case: valid payload but DB blows up → 503, not 500."""
        payload = {"name": "Mia", "target": "Data Analyst", "category": "Fresher"}
        with patch("backend.db_create_mentee", side_effect=Exception("disk full")):
            resp = self._post(client, payload)
        assert resp.status_code == 503

    def test_create_multiple_validation_errors_returned(self, client):
        """Edge case: name AND category missing → both errors listed in 'details'."""
        payload = {"target": "DevOps"}  # missing name and category
        resp = self._post(client, payload)
        assert resp.status_code == 400
        details = resp.get_json()["details"]
        assert len(details) >= 2  # at least name + category errors


# ══════════════════════════════════════════════════════════════════════════════
# ── UPDATE  PUT /api/mentees/<id> ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateMentee:

    def _put(self, client, mentee_id, payload):
        return client.put(
            f"/api/mentees/{mentee_id}",
            data=json.dumps(payload),
            content_type="application/json",
        )

    # ── Happy path ─────────────────────────────────────────────────────────────
    def test_update_progress_happy_path(self, client):
        """Happy path: update a single field (progress) returns updated mentee."""
        updated = {**_SAMPLE_MENTEE, "progress": 75}
        with patch("backend.db_update_mentee", return_value=updated):
            resp = self._put(client, KNOWN_ID, {"progress": 75})
        assert resp.status_code == 200
        assert resp.get_json()["mentee"]["progress"] == 75

    def test_update_multiple_fields(self, client):
        """Happy path: update name + skills simultaneously."""
        updated = {**_SAMPLE_MENTEE, "name": "Alice Smith",
                   "skills": ["Python", "TensorFlow"]}
        with patch("backend.db_update_mentee", return_value=updated):
            resp = self._put(client, KNOWN_ID,
                             {"name": "Alice Smith", "skills": ["Python", "TensorFlow"]})
        assert resp.status_code == 200

    def test_update_category_switcher(self, client):
        """Happy path: changing category from Fresher to Switcher."""
        updated = {**_SAMPLE_MENTEE, "category": "Switcher"}
        with patch("backend.db_update_mentee", return_value=updated):
            resp = self._put(client, KNOWN_ID, {"category": "Switcher"})
        assert resp.status_code == 200
        assert resp.get_json()["mentee"]["category"] == "Switcher"

    # ── Edge cases ─────────────────────────────────────────────────────────────
    def test_update_nonexistent_id_returns_404(self, client):
        """Edge case: UUID exists in correct format but not in DB → 404."""
        with patch("backend.db_update_mentee", return_value=None):
            resp = self._put(client, str(uuid.uuid4()), {"progress": 10})
        assert resp.status_code == 404

    def test_update_invalid_uuid_format_returns_400(self, client):
        """Edge case: garbage ID in path → 400 before hitting DB."""
        resp = self._put(client, "BAD-ID-$$", {"progress": 10})
        assert resp.status_code == 400

    def test_update_empty_body_returns_400(self, client):
        """Edge case: empty JSON body → 400 (nothing to update)."""
        resp = self._put(client, KNOWN_ID, {})
        assert resp.status_code == 400
        assert "empty" in resp.get_json()["error"].lower()

    def test_update_invalid_category_returns_400(self, client):
        """Edge case: invalid category value in update → 400."""
        resp = self._put(client, KNOWN_ID, {"category": "Manager"})
        assert resp.status_code == 400

    def test_update_progress_out_of_range_returns_400(self, client):
        """Edge case: progress = 999 → 400."""
        resp = self._put(client, KNOWN_ID, {"progress": 999})
        assert resp.status_code == 400

    def test_update_non_json_content_type_returns_415(self, client):
        """Edge case: form-encoded PUT → 415."""
        resp = client.put(f"/api/mentees/{KNOWN_ID}", data={"progress": 50})
        assert resp.status_code == 415

    def test_update_db_error_returns_503(self, client):
        """Edge case: valid update but DB fails → 503."""
        with patch("backend.db_update_mentee", side_effect=Exception("lock timeout")):
            resp = self._put(client, KNOWN_ID, {"progress": 50})
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# ── DELETE  DELETE /api/mentees/<id> ──────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteMentee:

    # ── Happy path ─────────────────────────────────────────────────────────────
    def test_delete_existing_mentee_returns_200(self, client):
        """Happy path: deleting a known mentee returns 200 with deleted ID."""
        with patch("backend.db_delete_mentee", return_value=True):
            resp = client.delete(f"/api/mentees/{KNOWN_ID}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "deleted"
        assert body["id"] == KNOWN_ID

    # ── Edge cases ─────────────────────────────────────────────────────────────
    def test_delete_nonexistent_id_returns_404(self, client):
        """Edge case: valid UUID not found in DB → 404."""
        with patch("backend.db_delete_mentee", return_value=False):
            resp = client.delete(f"/api/mentees/{str(uuid.uuid4())}")
        assert resp.status_code == 404

    def test_delete_invalid_uuid_format_returns_400(self, client):
        """Edge case: non-UUID path param → 400."""
        resp = client.delete("/api/mentees/12345-not-uuid")
        assert resp.status_code == 400

    def test_delete_db_error_returns_503(self, client):
        """Edge case: DB raises exception → 503."""
        with patch("backend.db_delete_mentee", side_effect=Exception("connection lost")):
            resp = client.delete(f"/api/mentees/{KNOWN_ID}")
        assert resp.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# ── Validation Unit Tests (_validate_mentee_payload) ──────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateMenteePayload:
    """Unit-test the validator helper directly (no HTTP overhead)."""

    from backend import _validate_mentee_payload as _v  # will be imported lazily

    def _v(self, data, partial=False):
        from backend import _validate_mentee_payload
        return _validate_mentee_payload(data, partial=partial)

    # ── Happy paths ────────────────────────────────────────────────────────────
    def test_valid_full_payload_returns_no_errors(self):
        """Happy path: a fully-specified correct payload has zero errors."""
        data = {
            "name": "Nora Bloom",
            "target": "Product Manager",
            "category": "Fresher",
            "progress": 45,
            "skills": ["SQL", "Figma"],
            "tasks": [{"title": "Read PM framework doc", "done": True}],
        }
        assert self._v(data) == []

    def test_valid_partial_update_single_field(self):
        """Happy path: partial=True with only 'progress' field has zero errors."""
        assert self._v({"progress": 80}, partial=True) == []

    # ── Edge cases ─────────────────────────────────────────────────────────────
    def test_name_is_integer_returns_error(self):
        """Edge case: name=123 (integer) → type error."""
        errors = self._v({"name": 123, "target": "SWE", "category": "Fresher"})
        assert any("string" in e for e in errors)

    def test_progress_as_string_digit_is_coerced(self):
        """Edge case: progress='50' (string) is coerced → validator should NOT report error."""
        errors = self._v({"name": "OK", "target": "SWE", "category": "Fresher", "progress": "50"})
        # '50' is coercible to int; validator accepts it
        assert not any("progress" in e for e in errors)

    def test_progress_non_numeric_string_returns_error(self):
        """Edge case: progress='high' → not convertible → error."""
        errors = self._v({"name": "OK", "target": "SWE", "category": "Fresher", "progress": "high"})
        assert any("progress" in e for e in errors)

    def test_tasks_not_list_returns_error(self):
        """Edge case: tasks='do stuff' (string) → array expected."""
        errors = self._v({"name": "A", "target": "B", "category": "Fresher", "tasks": "do stuff"})
        assert any("array" in e for e in errors)

    def test_too_many_skills_returns_error(self):
        """Edge case: 51 skills → exceeds limit of 50."""
        errors = self._v({
            "name": "A", "target": "B", "category": "Fresher",
            "skills": [f"Skill{i}" for i in range(51)],
        })
        assert any("50" in e for e in errors)

    def test_too_many_tasks_returns_error(self):
        """Edge case: 31 tasks → exceeds limit of 30."""
        errors = self._v({
            "name": "A", "target": "B", "category": "Fresher",
            "tasks": [{"title": f"Task {i}", "done": False} for i in range(31)],
        })
        assert any("30" in e for e in errors)

    def test_partial_skip_unset_fields(self):
        """Edge case: partial=True with unknown field only → no errors on required fields."""
        errors = self._v({"progress": 10}, partial=True)
        # Missing name/target/category are NOT checked when partial=True
        assert errors == []

    def test_category_case_sensitive(self):
        """Edge case: 'fresher' (lowercase) is not valid → must be 'Fresher'."""
        errors = self._v({"name": "A", "target": "B", "category": "fresher"})
        assert any("Fresher" in e or "Switcher" in e for e in errors)
