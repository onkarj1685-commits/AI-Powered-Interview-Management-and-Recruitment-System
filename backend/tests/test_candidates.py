def test_create_candidate(client):
    resp = client.post(
        "/candidates/",
        json={"full_name": "Alan Turing", "email": "alan@example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["full_name"] == "Alan Turing"
    assert data["email"] == "alan@example.com"
    assert "id" in data


def test_create_candidate_duplicate_email_fails(client, sample_candidate):
    resp = client.post(
        "/candidates/",
        json={"full_name": "Ada L.", "email": sample_candidate["email"]},
    )
    assert resp.status_code == 400


def test_get_candidate(client, sample_candidate):
    resp = client.get(f"/candidates/{sample_candidate['id']}")
    assert resp.status_code == 200
    assert resp.json()["email"] == sample_candidate["email"]


def test_get_candidate_not_found(client):
    resp = client.get("/candidates/9999")
    assert resp.status_code == 404


def test_list_candidates(client, sample_candidate):
    resp = client.get("/candidates/")
    assert resp.status_code == 200
    emails = [c["email"] for c in resp.json()]
    assert sample_candidate["email"] in emails


def test_update_candidate(client, sample_candidate):
    resp = client.patch(
        f"/candidates/{sample_candidate['id']}", json={"phone": "555-9999"}
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "555-9999"


def test_delete_candidate(client, sample_candidate):
    resp = client.delete(f"/candidates/{sample_candidate['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/candidates/{sample_candidate['id']}")
    assert resp.status_code == 404


def test_create_candidate_invalid_email(client):
    resp = client.post(
        "/candidates/", json={"full_name": "Bad Email", "email": "not-an-email"}
    )
    assert resp.status_code == 422
