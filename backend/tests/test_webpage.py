"""Reading a public page for "Tell your team about you": the words come back, the junk doesn't,
and the server can't be pointed at its own network."""

import httpx
import pytest

from app import webpage
from app.mcp_client import socket as webpage_dns

PAGE = """<html><head><title>Acme Coffee</title><meta name="description" content="Coffee subscriptions for offices.">
<style>.x{}</style><script>track()</script></head><body><nav>Home About Pricing</nav>
<h1>Great coffee at work</h1><p>We deliver fresh beans to 400 offices every week.</p>
<p>We deliver fresh beans to 400 offices every week.</p><footer>© Acme</footer></body></html>"""


def transport(routes):
    def handle(req: httpx.Request) -> httpx.Response:
        status, headers, body = routes[str(req.url)]
        return httpx.Response(status, headers=headers, text=body)
    return httpx.MockTransport(handle)


def test_reads_the_words_not_the_junk():
    t = transport({"https://acme.example/": (200, {"content-type": "text/html"}, PAGE)})
    r = webpage.read("acme.example/", allow_private=True, transport=t)
    assert r["title"] == "Acme Coffee" and r["url"] == "https://acme.example/"
    assert "Coffee subscriptions for offices." in r["text"] and "Great coffee at work" in r["text"]
    assert r["text"].count("400 offices") == 1
    assert not any(w in r["text"] for w in ("track()", "Pricing", "© Acme", ".x{}"))


def test_follows_redirects_and_checks_each_one(monkeypatch):
    t = transport({"https://acme.example/": (301, {"location": "/about"}, ""),
                   "https://acme.example/about": (200, {"content-type": "text/html"}, PAGE)})
    assert webpage.read("https://acme.example/", allow_private=True, transport=t)["url"] == "https://acme.example/about"
    public = lambda host, port: [(None, None, None, None, ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", port))]
    monkeypatch.setattr(webpage_dns, "getaddrinfo", public)
    t = transport({"https://acme.example/": (302, {"location": "http://127.0.0.1/admin"}, "")})
    with pytest.raises(webpage.PageError, match="private address"):
        webpage.read("https://acme.example/", allow_private=False, transport=t)


@pytest.mark.parametrize("url,status,kind,body,says", [
    ("https://www.linkedin.com/in/someone", 200, "text/html", PAGE, "LinkedIn"),
    ("https://acme.example/cv.pdf", 200, "application/pdf", "%PDF", "isn't a web page"),
    ("https://acme.example/gone", 404, "text/html", "", "404"),
    ("https://acme.example/app", 200, "text/html", "<div id=root></div>", "JavaScript"),
])
def test_says_plainly_what_went_wrong(url, status, kind, body, says):
    t = transport({url: (status, {"content-type": kind}, body)})
    with pytest.raises(webpage.PageError, match=says):
        webpage.read(url, allow_private=True, transport=t)


def test_endpoint_needs_a_user_and_refuses_private_hosts(client, make_user):
    assert client.post("/api/files/read-page", json={"url": "https://acme.example"}).status_code == 401
    r = make_user("alice").post("/api/files/read-page", json={"url": "http://127.0.0.1:9/"})
    assert r.status_code == 422 and "private address" in r.json()["detail"]
