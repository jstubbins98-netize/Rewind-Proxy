"""Snapshot search and routing regression tests (no archive network required)."""

import threading
import unittest
import urllib.request
from unittest.mock import Mock, patch

import proxy
import wayback


def capture(timestamp="20000101000000"):
    return {
        "timestamp": timestamp,
        "original": "http://example.com/",
        "url": f"https://web.archive.org/web/{timestamp}/http://example.com/",
    }


class SnapshotTests(unittest.TestCase):
    def test_cdx_query_and_pagination(self):
        rows = [["timestamp", "original"]] + [
            [f"20000101{i // 3600:02d}{i // 60 % 60:02d}{i % 60:02d}", "http://example.com/"]
            for i in range(51)
        ]
        response = Mock()
        response.json.return_value = rows
        with patch.object(wayback._session, "get", return_value=response) as get:
            results, more = wayback.find_snapshots("http://example.com/", 2)
        self.assertEqual(len(results), 50)
        self.assertTrue(more)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["offset"], "100")
        self.assertEqual(params["matchType"], "exact")
        response.raise_for_status.assert_called_once()

    def test_empty_and_invalid_responses(self):
        response = Mock()
        with patch.object(wayback._session, "get", return_value=response):
            response.json.return_value = []
            self.assertEqual(wayback.find_snapshots("http://example.com/"), ([], False))
            response.json.return_value = {"error": "unavailable"}
            with self.assertRaises(ValueError):
                wayback.find_snapshots("http://example.com/")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.server = proxy.ThreadingHTTPServer(("127.0.0.1", 0), proxy.RewindProxyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.finder = patch.object(proxy, "find_snapshots")
        self.find = self.finder.start()
        self.fetcher = patch.object(proxy, "fetch")
        self.fetch = self.fetcher.start()
        response = Mock()
        response.content = b"<html><body>Chosen archive</body></html>"
        response.headers = {"Content-Type": "text/html"}
        response.url = capture()["url"]
        response.status_code = 200
        response.reason = "OK"
        self.fetch.return_value = response

    def tearDown(self):
        self.fetcher.stop()
        self.finder.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path):
        return urllib.request.urlopen(self.base + path, timeout=3)

    def test_multiple_captures_and_selected_replay(self):
        self.find.return_value = ([capture(), capture("20010101000000")], False)
        with self.request("/go?url=example.com&year=2000&month=01&day=01") as response:
            body = response.read().decode()
        self.assertIn("Which archived page", body)
        self.assertIn("2001-01-01", body)
        self.assertIn('/r?url=', body)
        self.fetch.assert_not_called()
        with self.request("/r?url=" + urllib.parse.quote(capture()["url"], safe="")) as response:
            self.assertIn(b"Chosen archive", response.read())
        self.find.assert_called_once()
        self.fetch.assert_called_once()

    def test_single_capture_opens_directly(self):
        self.find.return_value = ([capture()], False)
        with self.request("/go?url=example.com") as response:
            self.assertIn(b"Chosen archive", response.read())
        self.fetch.assert_called_once()

    def test_pagination(self):
        self.find.return_value = ([capture(), capture("20010101000000")], True)
        with self.request("/go?url=example.com&page=1") as response:
            body = response.read().decode()
        self.find.assert_called_once_with("http://example.com", 1)
        self.assertIn("Previous captures", body)
        self.assertIn("More captures", body)

    def test_errors_are_visible(self):
        self.find.return_value = ([], False)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/go?url=example.com")
        self.assertEqual(error.exception.code, 404)
        self.find.side_effect = TimeoutError("upstream unavailable")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/go?url=example.com")
        self.assertEqual(error.exception.code, 502)
        self.fetch.assert_not_called()

    def test_proxy_navigation_and_asset_bypass(self):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        self.find.return_value = ([capture(), capture("20010101000000")], False)
        with patch.dict("os.environ", {"REWIND_HEADLESS": "1"}):
            connection.request("GET", "http://example.com/", headers={"Accept": "text/html"})
            response = connection.getresponse()
            self.assertIn(b"Which archived page", response.read())
        self.find.assert_called_once()
        self.find.reset_mock()
        connection.request("GET", "http://example.com/style.css", headers={"Accept": "*/*"})
        response = connection.getresponse()
        response.read()
        self.find.assert_not_called()
        self.fetch.assert_called_once()
        connection.close()


if __name__ == "__main__":
    unittest.main()
