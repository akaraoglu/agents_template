import unittest
from urllib import error
from unittest.mock import patch

from openclaw_agents.services.web_research import WebResearchService


class _FakeResponse:
    def __init__(self, body: str, *, url: str, content_type: str = "text/html") -> None:
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class WebResearchServiceTest(unittest.TestCase):
    def test_research_normalizes_duckduckgo_redirects_and_builds_citations(self) -> None:
        search_html = """
        <html>
          <body>
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">Alpha API Guide</a>
            <div class="result__snippet">Alpha weather API comparison.</div>
            <a class="result__a" href="https://example.org/beta">Beta Docs</a>
            <div class="result__snippet">Official beta forecast docs.</div>
          </body>
        </html>
        """
        alpha_html = "<html><head><title>Alpha API Guide</title></head><body><p>Alpha compares multiple public weather APIs.</p></body></html>"
        beta_html = "<html><head><title>Beta Docs</title></head><body><p>Beta documents official forecast feeds.</p></body></html>"

        def fake_urlopen(req, timeout=20):
            url = req.full_url
            if "duckduckgo.com/html/" in url:
                return _FakeResponse(search_html, url=url)
            if "example.com/alpha" in url:
                return _FakeResponse(alpha_html, url="https://example.com/alpha")
            if "example.org/beta" in url:
                return _FakeResponse(beta_html, url="https://example.org/beta")
            raise AssertionError(f"Unexpected URL: {url}")

        service = WebResearchService()
        with patch("openclaw_agents.services.web_research.request.urlopen", side_effect=fake_urlopen):
            packet = service.research("public weather api", search_limit=4, fetch_limit=2, max_chars=200)

        self.assertEqual(packet["results"][0]["url"], "https://example.com/alpha")
        self.assertEqual(packet["sources"][0]["domain"], "example.com")
        self.assertEqual(packet["sources"][1]["domain"], "example.org")
        self.assertEqual(packet["sources"][0]["title"], "Alpha API Guide")
        self.assertIn("[1] Alpha API Guide (example.com)", packet["citations"][0])
        self.assertIn("Alpha compares multiple public weather APIs.", packet["sources"][0]["content_excerpt"])

    def test_research_degrades_to_search_snippet_when_fetch_fails(self) -> None:
        search_html = """
        <html>
          <body>
            <a class="result__a" href="https://example.com/alpha">Alpha API Guide</a>
            <div class="result__snippet">Alpha weather API comparison.</div>
          </body>
        </html>
        """

        def fake_urlopen(req, timeout=20):
            url = req.full_url
            if "duckduckgo.com/html/" in url:
                return _FakeResponse(search_html, url=url)
            if "example.com/alpha" in url:
                raise error.URLError("temporary failure")
            raise AssertionError(f"Unexpected URL: {url}")

        service = WebResearchService(max_retries=0)
        with patch("openclaw_agents.services.web_research.request.urlopen", side_effect=fake_urlopen):
            packet = service.research("public weather api", search_limit=2, fetch_limit=1, max_chars=200)

        self.assertEqual(len(packet["sources"]), 1)
        self.assertEqual(packet["sources"][0]["content_type"], "search_result_snippet")
        self.assertEqual(packet["sources"][0]["title"], "Alpha API Guide")
        self.assertEqual(packet["failures"][0]["url"], "https://example.com/alpha")
        self.assertIn("Alpha weather API comparison.", packet["sources"][0]["content_excerpt"])


if __name__ == "__main__":
    unittest.main()
