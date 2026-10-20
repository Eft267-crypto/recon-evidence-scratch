#!/usr/bin/env python3
"""Phase 2 probe: fetch exactly 3 fixed News24 index URLs. No crawling."""
import argparse, hashlib, json, sys, tempfile
from pathlib import Path
import recon_capture as rc

PROBE_URLS = [
    "https://www.news24.com/sitemap",
    "https://www.news24.com/lottery/",
    "https://feeds.24.com/articles/news24/lottery/results/rss",
]
# Probe-only exact hosts (feeds.24.com is News24's own feed host).
rc.ALLOWLIST = frozenset(set(rc.ALLOWLIST) | {"feeds.24.com"})

def self_test():
    assert len(PROBE_URLS) == 3
    for u in PROBE_URLS:
        assert rc.exact_host(u) in rc.ALLOWLIST
    for bad in ("https://news24.com/sitemap", "http://www.news24.com/sitemap",
                "https://x.com/sa_lottery"):
        try: rc.exact_host(bad)
        except ValueError: pass
        else: raise AssertionError(bad)
    print("PROBE SELF-TEST PASS: 3 fixed URLs, exact hosts, bad hosts refused")

def probe(out):
    out.mkdir(parents=True, exist_ok=True)
    limiter = rc.RateLimiter()
    parsers, delays, audit = {}, {}, {"user_agent": rc.USER_AGENT,
                                      "robots": {}, "captures": []}
    for url in PROBE_URLS:
        host = rc.exact_host(url)
        if host not in parsers:
            p, rec, d = rc.load_robots(host, out, rc.fetch_no_redirect, limiter)
            parsers[host], delays[host], audit["robots"][host] = p, d, rec
        entry = {"url": url, "outcome": None}
        if not rc.permitted(url, parsers):
            entry["outcome"] = "ROBOTS_DENIED_OR_UNREADABLE"
        else:
            try:
                st, hd, body = rc.request_limited(url, host, rc.fetch_no_redirect,
                                                  limiter, delays[host])
                name = f"responses/{len(audit['captures'])+1:02d}-{st}.body"
                entry.update(rc.body_metadata(out, name, body))
                entry.update({"status": st, "headers": hd,
                              "outcome": "captured" if st == 200 else
                              ("redirected" if 300 <= st < 400 else "failed")})
            except Exception as exc:
                entry["outcome"] = "failed"; entry["error"] = type(exc).__name__
        audit["captures"].append(entry)
    (out / "audit.json").write_text(json.dumps(audit, indent=2))
    ok = sum(c["outcome"] == "captured" for c in audit["captures"])
    print({c["url"]: c["outcome"] for c in audit["captures"]})
    return 0 if ok else 2

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--output", default="probe-evidence")
    a = ap.parse_args()
    if a.self_test: self_test()
    elif a.probe: sys.exit(probe(Path(a.output)))
    else: ap.error("choose --self-test or --probe")
