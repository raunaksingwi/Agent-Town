"""The built frontend is served from frontend/dist, and nothing outside it."""

import os

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.mark.skipif(not os.path.isdir(main.DIST), reason="frontend not built")
@pytest.mark.parametrize("path", ["/..%2F..%2Fbackend%2Fpyproject.toml", "/%2e%2e/%2e%2e/backend/pyproject.toml",
                                  "/..%2f..%2fbackend/.env", "/assets/..%2F..%2F..%2Fbackend%2Fpyproject.toml"])
def test_no_files_from_outside_dist(path):
    r = TestClient(main.app).get(path)
    assert "[project]" not in r.text and "AGENTTOWN_" not in r.text


@pytest.mark.skipif(not os.path.isdir(main.DIST), reason="frontend not built")
def test_files_in_dist_and_the_app_for_everything_else():
    c = TestClient(main.app)
    assert c.get("/index.html").status_code == 200
    assert '<div id="root">' in c.get("/chat").text


@pytest.mark.skipif(not os.path.isdir(main.DIST), reason="frontend not built")
def test_head_like_get():
    c = TestClient(main.app)
    assert c.head("/").status_code == 200
    assert c.head("/chat").status_code == 200
