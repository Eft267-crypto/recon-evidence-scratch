#!/usr/bin/env python3
"""Pilot: 20 fixed News24 daily sub-sitemaps -> lottery pages for that date."""
import argparse, json, re, sys, tempfile
from pathlib import Path
import urllib.parse
import recon_capture as rc

DATES = ['2020-06-03','2020-09-12','2020-12-23','2021-04-03','2021-07-14',
 '2021-10-23','2022-02-05','2022-05-18','2022-08-27','2022-12-07',
 '2023-03-18','2023-06-28','2023-10-07','2024-01-17','2024-04-27',
 '2024-08-07','2024-11-16','2025-03-01','2025-06-11','2025-09-20']
HOST = "www.news24.com"
MAX_PAGES_PER_DATE = 3

def sub_url(d):
    y, m, dd = d.split("-")
    return f"https://{HOST}/sitemapindex/0/{y}/{m}/{dd}"

def pick_pages(xml_text, d):
    """Lottery result URLs for exactly this date, on the exact host only."""
    stamp = d.replace("-", "")
    out = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml_text):
        p = urllib.parse.urlsplit(loc.strip())
        if (p.scheme == "https" and p.hostname == HOST and not p.query
                and "/lottery/" in p.path.lower() and stamp in p.path
                and "lotto" in p.path.lower() and loc not in out):
            out.append(loc.strip())
    return out[:MAX_PAGES_PER_DATE]

def self_test():
    assert len(DATES) == 20 and sub_url("2020-06-03").endswith("/sitemapindex/0/2020/06/03") and "/news24/" not in sub_url("2020-06-03")
    xml = ("<urlset><url><loc>https://www.news24.com/lottery/results/a-lotto-20200603</loc></url>"
           "<url><loc>https://evil.example/lottery/lotto-20200603</loc></url>"
           "<url><loc>https://www.news24.com/sport/x-20200603</loc></url>"
           "<url><loc>http://www.news24.com/lottery/lotto-20200603</loc></url>"
           "<url><loc>https://www.news24.com/lottery/lotto-20200604</loc></url></urlset>")
    assert pick_pages(xml, "2020-06-03") == ["https://www.news24.com/lottery/results/a-lotto-20200603"]
    rc.exact_host(sub_url("2020-06-03"))
    print("PILOT SELF-TEST PASS: 20 dates, URL builder, host/date/lottery filter")

def pilot(out):
    out.mkdir(parents=True, exist_ok=True)
    lim = rc.RateLimiter()
    parser, rec, delay = rc.load_robots(HOST, out, rc.fetch_no_redirect, lim)
    audit = {"user_agent": rc.USER_AGENT, "robots": rec, "dates": []}
    n = 0
    def get(url, kind):
        nonlocal n
        e = {"url": url, "kind": kind, "outcome": None}
        if parser is None or not rc.permitted(url, {HOST: parser}):
            e["outcome"] = "ROBOTS_DENIED_OR_UNREADABLE"; return e, None
        try:
            st, hd, body = rc.request_limited(url, HOST, rc.fetch_no_redirect, lim, delay)
            n += 1
            e.update(rc.body_metadata(out, f"responses/{n:03d}-{kind}-{st}.body", body))
            e["status"] = st
            e["location"] = rc.header_value(hd, "Location")
            e["outcome"] = "captured" if st == 200 else ("redirected" if 300 <= st < 400 else "failed")
            return e, body
        except Exception as exc:
            e["outcome"] = "failed"; e["error"] = type(exc).__name__; return e, None
    for d in DATES:
        row = {"date": d, "sitemap": None, "pages": []}
        e, body = get(sub_url(d), "sitemap")
        row["sitemap"] = e
        if body is not None and e["outcome"] == "captured":
            urls = pick_pages(body.decode("utf-8", "replace"), d)
            row["selected"] = urls
            for u in urls:
                pe, _ = get(u, "page"); row["pages"].append(pe)
        audit["dates"].append(row)
    (out / "audit.json").write_text(json.dumps(audit, indent=2))
    got = sum(1 for r in audit["dates"] for p in r["pages"] if p["outcome"] == "captured")
    print("sitemaps ok:", sum(r["sitemap"]["outcome"] == "captured" for r in audit["dates"]),
          "pages captured:", got)
    return 0 if got else 2

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--output", default="pilot-evidence")
    a = ap.parse_args()
    if a.self_test: self_test()
    elif a.pilot: sys.exit(pilot(Path(a.output)))
    else: ap.error("choose --self-test or --pilot")
