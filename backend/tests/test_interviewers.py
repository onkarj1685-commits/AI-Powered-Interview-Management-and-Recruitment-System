def test_create_interviewer(client):
    resp = client.post(
        "/interviewers/",
        json={"full_name": "Margaret Hamilton", "email": "margaret@example.com"},
    )
    assert resp.status_code == 201
    assert resp.json()["full_name"] == "Margaret Hamilton"


def test_list_interviewers(client, sample_interviewer):
    resp = client.get("/interviewers/")
    assert resp.status_code == 200
    emails = [i["email"] for i in resp.json()]
    assert sample_interviewer["email"] in emails


def test_get_interviewer_not_found(client):
    resp = client.get("/interviewers/424242")
    assert resp.status_code == 404


def test_update_interviewer(client, sample_interviewer):
    resp = client.patch(
        f"/interviewers/{sample_interviewer['id']}", json={"title": "Principal Engineer"}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Principal Engineer"


def test_delete_interviewer(client, sample_interviewer):
    resp = client.delete(f"/interviewers/{sample_interviewer['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/interviewers/{sample_interviewer['id']}")
    assert resp.status_code == 404
