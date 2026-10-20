#!/usr/bin/env python3
"""LotteryExtreme probe: exactly 3 fixed URLs. No crawling, no following links."""
import argparse, json, sys
from pathlib import Path
import recon_capture as rc

HOST = "www.lotteryextreme.com"
PROBE_URLS = [
    "https://www.lotteryextreme.com/south-africa/lotto-plus-2/results-history",
    "https://www.lotteryextreme.com/south-africa/lotto/results-history",
    "https://www.lotteryextreme.com/south-africa/lotto-plus-2/statistics",
]

def self_test():
    assert len(PROBE_URLS) == 3
    for u in PROBE_URLS:
        assert rc.exact_host(u) == HOST
    for bad in ("https://lotteryextreme.com/x", "http://www.lotteryextreme.com/x",
                "https://www.lotteryextreme.com:8443/x", "https://x.com/a"):
        try: rc.exact_host(bad)
        except ValueError: pass
        else: raise AssertionError(bad)
    print("LE PROBE SELF-TEST PASS: 3 fixed URLs, exact host, bad hosts refused")

def probe(out):
    out.mkdir(parents=True, exist_ok=True)
    lim = rc.RateLimiter()
    parser, rec, delay = rc.load_robots(HOST, out, rc.fetch_no_redirect, lim)
    audit = {"user_agent": rc.USER_AGENT, "robots": rec, "captures": []}
    for i, url in enumerate(PROBE_URLS, 1):
        e = {"url": url, "outcome": None}
        if parser is None or not rc.permitted(url, {HOST: parser}):
            e["outcome"] = "ROBOTS_DENIED_OR_UNREADABLE"
        else:
            try:
                st, hd, body = rc.request_limited(url, HOST, rc.fetch_no_redirect, lim, delay)
                e.update(rc.body_metadata(out, f"responses/{i:02d}-{st}.body", body))
                e.update({"status": st, "location": rc.header_value(hd, "Location"),
                          "outcome": "captured" if st == 200 else
                          ("redirected" if 300 <= st < 400 else "failed")})
            except Exception as exc:
                e["outcome"] = "failed"; e["error"] = type(exc).__name__
        audit["captures"].append(e)
    (out / "audit.json").write_text(json.dumps(audit, indent=2))
    print({c["url"]: c["outcome"] for c in audit["captures"]})
    return 0 if any(c["outcome"] == "captured" for c in audit["captures"]) else 2

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--output", default="le-evidence")
    a = ap.parse_args()
    if a.self_test: self_test()
    elif a.probe: sys.exit(probe(Path(a.output)))
    else: ap.error("choose --self-test or --probe")
