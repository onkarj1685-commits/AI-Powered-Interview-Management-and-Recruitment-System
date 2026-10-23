def test_create_job(client):
    resp = client.post(
        "/jobs/",
        json={"title": "Data Scientist", "department": "Data", "status": "open"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Data Scientist"
    assert data["status"] == "open"


def test_get_job(client, sample_job):
    resp = client.get(f"/jobs/{sample_job['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == sample_job["title"]


def test_get_job_not_found(client):
    resp = client.get("/jobs/12345")
    assert resp.status_code == 404


def test_list_jobs(client, sample_job):
    resp = client.get("/jobs/")
    assert resp.status_code == 200
    titles = [j["title"] for j in resp.json()]
    assert sample_job["title"] in titles


def test_update_job_status(client, sample_job):
    resp = client.patch(f"/jobs/{sample_job['id']}", json={"status": "closed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_delete_job(client, sample_job):
    resp = client.delete(f"/jobs/{sample_job['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/jobs/{sample_job['id']}")
    assert resp.status_code == 404


def test_create_job_invalid_status(client):
    resp = client.post(
        "/jobs/", json={"title": "Broken Job", "status": "not_a_real_status"}
    )
    assert resp.status_code == 422
