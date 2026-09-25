"""
Playwright browser automation against a local page, using a real Chromium.

Runs when Chromium is available: set CLAP_TEST_CHROMIUM to its executable
(CI container: /opt/pw-browsers/chromium), or have `playwright install chromium` done.
"""

import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests import _env  # noqa: F401

from tools import browser

PAGE = b"""<!doctype html><title>CLAP test page</title>
<h1 id="h">Hello from the test page</h1>
<input id="q" name="q"><button onclick="document.getElementById('h').textContent='Clicked: '+document.getElementById('q').value">Go</button>"""


class Page(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


@unittest.skipUnless(os.environ.get("CLAP_TEST_CHROMIUM") or os.environ.get("CLAP_TEST_BROWSER"), "no Chromium configured")
class BrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/"
        options = {"headless": True}
        if os.environ.get("CLAP_TEST_CHROMIUM"):
            options["executable_path"] = os.environ["CLAP_TEST_CHROMIUM"]
        browser.LAUNCH_OPTIONS = options

    @classmethod
    def tearDownClass(cls):
        browser.browser_close()
        cls.server.shutdown()

    def test_full_flow_across_threads(self):
        # Chrome channel is absent here: this also exercises the Chromium fallback.
        nav = browser.browser_navigate(self.url)
        self.assertTrue(nav["success"], nav)
        self.assertEqual(nav["title"], "CLAP test page")

        # A different thread (like a second voice/web command) must still work.
        results = {}
        t = threading.Thread(target=lambda: results.update(browser.browser_get_text("#h")))
        t.start()
        t.join(30)
        self.assertEqual(results.get("text"), "Hello from the test page")

        self.assertTrue(browser.browser_fill("#q", "CLAP")["success"])
        self.assertTrue(browser.browser_click(text="Go")["success"])
        self.assertEqual(browser.browser_get_text("#h")["text"], "Clicked: CLAP")

        shot = browser.browser_screenshot()
        self.assertTrue(shot["success"])
        self.assertTrue(os.path.getsize(shot["saved_to"]) > 1000)
        self.assertNotIn("base64", shot)
        os.unlink(shot["saved_to"])

        self.assertEqual(browser.browser_current_url()["url"], self.url)


if __name__ == "__main__":
    unittest.main()
