from fastapi.testclient import TestClient

from partforge.app import create_app


def test_health_is_public():
    c = TestClient(create_app(token="x"))
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_token_required():
    c = TestClient(create_app(token="x"))
    assert c.get("/api/settings").status_code == 401
    assert c.get("/api/settings", headers={"X-PartForge-Token": "x"}).status_code == 200
    assert c.get("/api/settings", params={"token": "x"}).status_code == 200


def test_workspace_lifecycle(bare_client, tmp_path):
    target = tmp_path / "Lib"
    r = bare_client.post("/api/workspace/create", json={"path": str(target), "name": "Meine Bibliothek", "with_examples": False})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["name"] == "Meine Bibliothek"
    assert (target / "partforge.json").is_file()
    for folder in ("Symbols", "Footprints", "3D", "Datasheets", "Backups", "Exports"):
        assert (target / folder).is_dir()
    assert bare_client.get("/api/workspace").json()["root"] == str(target.resolve())
    recent = bare_client.get("/api/workspace/recent").json()
    assert recent[0]["path"] == str(target.resolve())
    assert bare_client.post("/api/workspace/create", json={"path": str(target)}).status_code == 409
    assert bare_client.post("/api/workspace/close").json()["ok"] is True
    assert bare_client.get("/api/workspace").json() is None
    assert bare_client.post("/api/workspace/open", json={"path": str(target)}).status_code == 200
    bare_client.post("/api/workspace/close")


def test_jobs_roundtrip():
    from partforge.jobs import JobManager

    mgr = JobManager(max_workers=1)

    def work(ctx, n):
        for i in range(n):
            ctx.progress(i / n, f"Schritt {i}")
            ctx.log(f"log {i}")
        return {"done": n}

    job = mgr.run_sync("test", "Testjob", work, 3)
    assert job.status == "done"
    assert job.result == {"done": 3}
    assert job.progress == 1.0
    assert len(job.log) == 3

    def boom(ctx):
        raise ValueError("kaputt")

    failed = mgr.run_sync("test", "Fehler", boom)
    assert failed.status == "failed"
    assert "kaputt" in failed.error
