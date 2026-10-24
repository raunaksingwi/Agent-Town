"""Read a public web page as plain text, so a person can hand their agents their company's website
or About page instead of typing it out. Standard library HTML parsing on purpose: we want the words,
not the layout."""

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from .mcp_client import McpError, guard_url

TIMEOUT = 10.0
MAX_BYTES = 2_000_000
MAX_TEXT = 15_000
MAX_REDIRECTS = 4
SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "form", "button", "iframe", "template", "head"}
BLOCK = {"p", "div", "section", "article", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "header", "main", "blockquote"}
# sites that refuse to be read by other servers: say so up front instead of failing oddly
WALLED = {"linkedin.com": "LinkedIn", "facebook.com": "Facebook", "instagram.com": "Instagram", "x.com": "X", "twitter.com": "X"}


class PageError(Exception):
    pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.description, self.parts, self.skip, self.in_title = "", "", [], 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("name") or a.get("property") or "").lower() in ("description", "og:description"):
            self.description = self.description or (a.get("content") or "").strip()
        if tag == "title":
            self.in_title = True
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        out, seen = [], set()
        for line in lines:
            if len(line) < 3 or line in seen:         # menus and cookie banners repeat; one-word crumbs say nothing
                continue
            seen.add(line)
            out.append(line)
        return "\n".join(out)


def read(url: str, allow_private: bool = False, transport: httpx.BaseTransport | None = None) -> dict:
    """{"url", "title", "text"} of a page. Every redirect is checked again, so a public page can't
    bounce the request into this server's own network."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    for domain, name in WALLED.items():
        if host == domain or host.endswith("." + domain):
            raise PageError(f"{name} doesn't let other sites read its pages. Copy the text you want and paste it instead.")
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport, headers={"User-Agent": "AgentTown/1.0 (reads a page its owner asked for)"}) as c:
            for _ in range(MAX_REDIRECTS + 1):
                guard_url(url, allow_private)
                with c.stream("GET", url) as r:
                    if r.is_redirect and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        raise PageError(f"The page answered {r.status_code}. Is the address right, and is the page public?")
                    kind = r.headers.get("content-type", "")
                    if "html" not in kind and "text/plain" not in kind:
                        raise PageError("That isn't a web page (it looks like a file). Paste its text instead.")
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    html = body.decode(r.encoding or "utf-8", errors="replace")
                    break
            else:
                raise PageError("That page redirects too many times.")
    except McpError as e:
        raise PageError(str(e)) from e
    except httpx.HTTPError as e:
        raise PageError(f"Couldn't reach that page ({type(e).__name__}).") from e

    if "text/plain" in kind:
        title, text = "", html
    else:
        p = _Text()
        p.feed(html)
        title = " ".join(p.title.split())
        text = "\n".join(x for x in (p.description, p.text()) if x)
    text = text.strip()[:MAX_TEXT]
    if len(text) < 40:
        raise PageError("That page has almost no text we can read (it may need JavaScript). Paste its text instead.")
    return {"url": url, "title": title, "text": text}
