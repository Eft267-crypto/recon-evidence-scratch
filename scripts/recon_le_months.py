#!/usr/bin/env python3
"""LotteryExtreme month archive capture: one POST per requested month, fixed list only."""
import argparse, json, re, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import recon_capture as rc

HOST = "www.lotteryextreme.com"
PATH = "/south-africa/lotto/results-history"
URL = f"https://{HOST}{PATH}"
MAX_MONTHS = 40
ALL_MONTHS = [f"{y}-{m:02d}" for y in range(2017, 2026) for m in range(1, 13)
              if (y, m) >= (2017, 8)]

def parse_months(text):
    months = [m.strip() for m in text.split(",") if m.strip()]
    if not months or len(months) > MAX_MONTHS or len(set(months)) != len(months):
        raise SystemExit("bad months list")
    for m in months:
        if not re.fullmatch(r"\d{4}-\d{2}", m) or m not in ALL_MONTHS:
            raise SystemExit(f"month not in fixed list: {m}")
    return months

def post_no_redirect(month):
    data = urllib.parse.urlencode({"mode": "month", "year_month": month}).encode()
    req = urllib.request.Request(URL, data=data, method="POST", headers={
        "User-Agent": rc.USER_AGENT, "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded"})
    opener = urllib.request.build_opener(rc.NoRedirect())
    try:
        with opener.open(req, timeout=rc.TIMEOUT_SECONDS) as r:
            return r.status, list(r.headers.items()), r.read()
    except urllib.error.HTTPError as exc:
        try: body = exc.read()
        finally: exc.close()
        return exc.code, list(exc.headers.items()), body

def self_test():
    assert len(ALL_MONTHS) == 101 and ALL_MONTHS[0] == "2017-08" and ALL_MONTHS[-1] == "2025-12"
    assert rc.exact_host(URL) == HOST
    assert parse_months("2017-12,2018-01,2019-01") == ["2017-12", "2018-01", "2019-01"]
    for bad in ("2017-07", "2026-01", "2018-1", "x", "2018-01,2018-01", ""):
        try: parse_months(bad)
        except SystemExit: pass
        else: raise AssertionError(bad)
    try: parse_months(",".join(ALL_MONTHS[:41]))
    except SystemExit: pass
    else: raise AssertionError("limit")
    print("LE MONTHS SELF-TEST PASS: fixed month list, validation, host")

def run(out, months):
    out.mkdir(parents=True, exist_ok=True)
    lim = rc.RateLimiter()
    parser, rec, delay = rc.load_robots(HOST, out, rc.fetch_no_redirect, lim)
    audit = {"user_agent": rc.USER_AGENT, "robots": rec, "method": "POST",
             "url": URL, "captures": []}
    for i, month in enumerate(months, 1):
        e = {"month": month, "outcome": None}
        if parser is None or not rc.permitted(URL, {HOST: parser}):
            e["outcome"] = "ROBOTS_DENIED_OR_UNREADABLE"
        else:
            try:
                st, hd, body = rc.request_limited(
                    month, HOST, lambda m: post_no_redirect(m), lim, delay)
                e.update(rc.body_metadata(out, f"responses/{i:03d}-{month}-{st}.body", body))
                e.update({"status": st, "location": rc.header_value(hd, "Location"),
                          "outcome": "captured" if st == 200 else
                          ("redirected" if 300 <= st < 400 else "failed")})
            except Exception as exc:
                e["outcome"] = "failed"; e["error"] = type(exc).__name__
        audit["captures"].append(e)
    (out / "audit.json").write_text(json.dumps(audit, indent=2))
    print({c["month"]: c["outcome"] for c in audit["captures"]})
    return 0 if any(c["outcome"] == "captured" for c in audit["captures"]) else 2

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--months", default="2017-12,2018-01,2019-01")
    ap.add_argument("--output", default="lem-evidence")
    a = ap.parse_args()
    if a.self_test: self_test()
    elif a.run: sys.exit(run(Path(a.output), parse_months(a.months)))
    else: ap.error("choose --self-test or --run")
