#!/usr/bin/env python3
"""Fixed-list raw evidence capture. No crawling, parsing, or CSV output."""

import argparse
import hashlib
import json
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.robotparser import RobotFileParser

REQUESTED_URLS = [
    "https://www.ewn.co.za/2024/12/29/lotto-results-saturday-28-december-2024",
    "https://www.ewn.co.za/2024/01/28/lotto-results-saturday-27-january-2024",
    "https://www.ewn.co.za/2025/01/09/lotto-results-wednesday-8-january-2025",
    "https://www.gauteng.net/whats-on-g/ithuba-lotto-results-for-16-08-2025/",
    "https://sundayworld.co.za/news/search-is-on-for-lucky-r7-million-lotto-jackpot-winner/",
    "https://www.lotteryextreme.com/south_africa/lottoplus2-results_history",
    "https://lotteryguru.com/south-africa-lottery-results/za-lotto-plus-2",
    "https://www.news24.com/lottery/results/lotto-results-saturday-december-30-20171230",
    "https://www.news24.com/lottery/lotto-results-saturday-january-13-20180113",
    "https://www.news24.com/Lottery/here-are-the-results-for-the-saturday-29-december-lottery-draw-20181229",
    "https://www.news24.com/Lottery/here-are-the-winning-numbers-for-the-powerball-and-powerball-plus-draws-for-tuesday-january-8-20190108",
    "https://www.news24.com/lottery/results/here-are-the-results-for-the-saturday-12-january-lottery-draw-20190112",
    "https://www.news24.com/lottery/results/your-lotto-and-lotto-plus-results-20191123-15",
    "https://www.news24.com/lottery/results/here-are-lotto-and-lotto-plus-results-20200111",
    "https://www.news24.com/lottery/results/wednesdays-lotto-and-lotto-plus-results-20200115-9",
    "https://www.news24.com/lottery/results/daily-lotto-wednesdays-results-20200129-2",
    "https://www.news24.com/lottery/results/here-are-your-lotto-and-lotto-plus-results-20201216-120",
    "https://www.news24.com/lottery/results/your-lotto-and-lotto-plus-results-20190803",
    "https://www.news24.com/lottery/results/all-your-powerball-results-20190802",
]

ALLOWLIST = frozenset({
    "www.ewn.co.za",
    "www.gauteng.net",
    "sundayworld.co.za",
    "www.lotteryextreme.com",
    "lotteryguru.com",
    "www.news24.com",
})

BLOCKED_HOSTS = frozenset({
    "za.national-lottery.com",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
})

MIN_DELAY = 2.0
TIMEOUT_SECONDS = 12
USER_AGENT = (
    "RECON-Raw-Evidence-Capture/1.0 "
    "(+https://github.com/Eft267-crypto/recon-evidence-scratch)"
)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return 3xx responses to the caller; never follow Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class RateLimiter:
    """Minimum start spacing based on the previous request's completion."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock = clock
        self.sleep = sleep
        self.finished = {}

    def wait(self, host, delay):
        delay = max(MIN_DELAY, float(delay))
        previous = self.finished.get(host)
        if previous is not None:
            remaining = delay - (self.clock() - previous)
            if remaining > 0:
                self.sleep(remaining)

    def mark_finished(self, host):
        self.finished[host] = self.clock()

def exact_host(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise ValueError("HTTPS required")
    if parts.username or parts.password:
        raise ValueError("URL credentials forbidden")
    if parts.port not in (None, 443):
        raise ValueError("Non-standard port forbidden")
    host = parts.hostname
    if not host or host not in ALLOWLIST or host in BLOCKED_HOSTS:
        raise ValueError(f"Host not exactly allowlisted: {host}")
    return host

def robots_url(host):
    if host not in ALLOWLIST or host in BLOCKED_HOSTS:
        raise ValueError("Robots host not allowlisted")
    return f"https://{host}/robots.txt"

def fetch_no_redirect(url):
    """Return status, original header pairs and response bytes."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            return (
                response.status,
                list(response.headers.items()),
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        # With redirects disabled, 3xx arrives here too. Preserve its body.
        try:
            body = exc.read()
        finally:
            exc.close()
        return exc.code, list(exc.headers.items()), body

def request_limited(url, host, fetcher, limiter, delay=MIN_DELAY):
    limiter.wait(host, max(MIN_DELAY, float(delay)))
    try:
        return fetcher(url)
    finally:
        limiter.mark_finished(host)

def header_value(headers, wanted):
    for key, value in headers:
        if key.lower() == wanted.lower():
            return value
    return None

def save_bytes(root, relative, body):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)  # No decoding, newline conversion or rewriting.
    return str(relative)

def body_metadata(root, relative, body):
    filename = save_bytes(root, relative, body)
    return {
        "body_file": filename,
        "byte_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }

def load_robots(host, output_dir, fetcher, limiter):
    """One robots request; save, hash and parse that same response body."""
    url = robots_url(host)
    record = {
        "robots_url": url,
        "status": None,
        "headers": [],
        "decision": "FAIL_CLOSED",
    }

    try:
        status, headers, body = request_limited(
            url, host, fetcher, limiter, MIN_DELAY
        )
        record.update({
            "status": status,
            "headers": headers,
            "location": header_value(headers, "Location"),
        })
        record.update(body_metadata(
            output_dir, f"robots/{host}.robots.txt", body
        ))

        # A 301, any other 3xx, 403, 404, 5xx, etc. fails closed.
        if status != 200:
            record["reason"] = "ROBOTS_HTTP_STATUS_NOT_200"
            return None, record, 0.0

        # Parse the exact bytes already saved and hashed above.
        text = body.decode("utf-8", errors="strict")
        parser = RobotFileParser()
        parser.set_url(url)
        parser.parse(text.splitlines())

        crawl_delay = parser.crawl_delay(USER_AGENT) or 0.0
        record["crawl_delay_seconds"] = crawl_delay
        record["decision"] = "LOADED"
        return parser, record, float(crawl_delay)

    except Exception as exc:
        record["error"] = type(exc).__name__
        record["reason"] = "ROBOTS_UNREADABLE_OR_UNPARSABLE"
        return None, record, 0.0

def permitted(url, parser_by_host):
    host = exact_host(url)
    parser = parser_by_host.get(host)
    if parser is None:
        return False
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parser.can_fetch(USER_AGENT, path)

def self_test():
    # All tests use fake responses and a fake clock; no network access.
    assert len(REQUESTED_URLS) == 19
    assert {exact_host(url) for url in REQUESTED_URLS} == ALLOWLIST

    fake_text = (
        "User-agent: *\n"
        "Disallow: /private/\n"
        "Crawl-delay: 5\n"
    )
    fake_parsers = {}
    for host in ALLOWLIST:
        parser = RobotFileParser()
        parser.set_url(robots_url(host))
        parser.parse(fake_text.splitlines())
        fake_parsers[host] = parser

    for url in REQUESTED_URLS:
        assert exact_host(url) in ALLOWLIST
        assert permitted(url, fake_parsers), f"Unexpected denial: {url}"

    assert not permitted(
        "https://www.news24.com/private/test", fake_parsers
    )

    for forbidden in (
        "https://za.national-lottery.com/robots.txt",
        "https://news24.com/robots.txt",
        "https://ewn.co.za/robots.txt",
        "https://gauteng.net/robots.txt",
        "https://lotteryextreme.com/robots.txt",
        "https://x.com/sa_lottery",
        "https://twitter.com/sa_lottery",
    ):
        try:
            exact_host(forbidden)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Forbidden host accepted: {forbidden}")

    # A robots redirect must fail closed, while retaining Location and body.
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        redirect_body = b"robots redirect response"
        def redirect_fetch(_url):
            return 301, [("Location", "https://elsewhere.invalid/robots.txt")], redirect_body

        parser, audit, _ = load_robots(
            "www.news24.com", root, redirect_fetch,
            RateLimiter(clock=lambda: 0.0, sleep=lambda _s: None),
        )
        saved = (root / audit["body_file"]).read_bytes()
        assert parser is None
        assert audit["decision"] == "FAIL_CLOSED"
        assert audit["status"] == 301
        assert audit["location"] == "https://elsewhere.invalid/robots.txt"
        assert saved == redirect_body
        assert audit["sha256"] == hashlib.sha256(redirect_body).hexdigest()
        assert audit["byte_length"] == len(redirect_body)

    # Fake-clock proof: requests to one host are spaced by at least 2 seconds.
    now = [0.0]
    sleeps = []
    def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(clock=lambda: now[0], sleep=fake_sleep)
    def fake_response(_url):
        return 200, [], b"ok"

    request_limited(
        "https://www.news24.com/robots.txt", "www.news24.com",
        fake_response, limiter, MIN_DELAY,
    )
    request_limited(
        "https://www.news24.com/next", "www.news24.com",
        fake_response, limiter, MIN_DELAY,
    )
    assert sleeps == [2.0], f"Unexpected fake-clock sleeps: {sleeps}"

    # Crawl-delay uses the larger value, not a value below the minimum.
    assert max(MIN_DELAY, fake_parsers["www.news24.com"].crawl_delay(USER_AGENT)) == 5.0

    # Verify the robots body is saved and hashed from the same single response.
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        original = b"User-agent: *\r\nDisallow: /private/\r\n"
        calls = []
        def body_fetch(_url):
            calls.append(_url)
            return 200, [("Content-Type", "text/plain")], original

        parser, audit, _ = load_robots(
            "www.news24.com", root, body_fetch,
            RateLimiter(clock=lambda: 0.0, sleep=lambda _s: None),
        )
        assert parser is not None
        assert len(calls) == 1
        assert (root / audit["body_file"]).read_bytes() == original
        assert audit["byte_length"] == len(original)
        assert audit["sha256"] == hashlib.sha256(original).hexdigest()

    print("SELF-TEST PASS: allowlist, denial, blocked hosts, 301 fail-closed, "
          "fake-clock delay, single-request robots body and SHA-256")

def capture(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter()
    parser_by_host = {}
    crawl_delays = {}
    robots_audit = {}

    audit = {
        "requested_urls": REQUESTED_URLS,
        "user_agent": USER_AGENT,
        "robots": robots_audit,
        "captures": [],
        "parsing_performed": False,
        "crawling_performed": False,
        "bulk_csv_created": False,
    }

    for host in sorted(ALLOWLIST):
        parser, record, crawl_delay = load_robots(
            host, output_dir, fetch_no_redirect, limiter
        )
        parser_by_host[host] = parser
        crawl_delays[host] = crawl_delay
        robots_audit[host] = record

    consecutive_limits = {host: 0 for host in ALLOWLIST}
    stopped_hosts = set()
    counts = {
        "captured": 0,
        "robots_denied": 0,
        "redirected": 0,
        "failed": 0,
    }

    for index, url in enumerate(REQUESTED_URLS, start=1):
        entry = {"index": index, "url": url}
        try:
            host = exact_host(url)

            if host in stopped_hosts:
                entry["decision"] = "FAILED_HOST_STOPPED_AFTER_403_429"
                counts["failed"] += 1
                audit["captures"].append(entry)
                continue

            if not permitted(url, parser_by_host):
                entry["decision"] = "ROBOTS_DENIED_OR_UNREADABLE"
                counts["robots_denied"] += 1
                audit["captures"].append(entry)
                continue

            status, headers, body = request_limited(
                url, host, fetch_no_redirect, limiter,
                max(MIN_DELAY, crawl_delays.get(host, 0.0)),
            )
            entry.update({
                "status": status,
                "headers": headers,
                "location": header_value(headers, "Location"),
            })

            if status in (403, 429):
                consecutive_limits[host] += 1
                if consecutive_limits[host] >= 2:
                    stopped_hosts.add(host)
            else:
                consecutive_limits[host] = 0

            relative = f"responses/{index:02d}-{status}.body"
            entry.update(body_metadata(output_dir, relative, body))

            if 300 <= status < 400:
                # Record Location and body; never follow the redirect.
                entry["decision"] = "REDIRECT_NOT_FOLLOWED"
                counts["redirected"] += 1
            elif status == 200:
                entry["decision"] = "RAW_CAPTURED"
                counts["captured"] += 1
            else:
                entry["decision"] = "FAILED_HTTP_STATUS"
                counts["failed"] += 1

        except Exception as exc:
            entry["decision"] = "FAILED_REQUEST_OR_VALIDATION"
            entry["error"] = type(exc).__name__
            counts["failed"] += 1

        audit["captures"].append(entry)

    audit["outcome"] = counts
    audit_path = output_dir / "audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit["outcome"], sort_keys=True))

    # Partial capture is reportable, not a script failure.
    # Zero captured URLs is a failure; artifact upload still runs in workflow.
    return 2 if counts["captured"] == 0 else 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--output", default="recon-evidence")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.capture:
        return capture(Path(args.output))
    parser.error("Specify --self-test or --capture")

if __name__ == "__main__":
    sys.exit(main())
