"""Bootstrap a live CreativeGate deployment from a ground-truth corpus.

Stdlib-only, narrated. Against a fresh (empty) deployment this performs the
three data steps of the smoketest (see SMOKETEST.md for what each means):

  1. upload the corpus as the named ground-truth set
     (gives the predictor training data and the judge its anchors);
  2. run every corpus artifact through the funnel
     (records what each rung *predicts* for artifacts whose truth we know);
  3. report the known outcomes to /ground-truth
     (the harness joins predictions to outcomes and measures each rung's
      correlation — fusion weights now exist, and verdicts become weighted).

Usage:
  CREATIVEGATE_URL=https://your-app.up.railway.app \\
  CREATIVEGATE_API_TOKEN=... \\
  python examples/bootstrap_calibration.py [path/to/corpus.json]
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("CREATIVEGATE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("CREATIVEGATE_API_TOKEN", "")
CORPUS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "ground-truth-example.json")


def call(method: str, path: str, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main() -> None:
    corpus = json.load(open(CORPUS))
    records = corpus["records"]
    print(f"gate: {BASE}  ·  corpus: {corpus['name']} ({len(records)} records)")

    print("\n[1/3] Uploading the ground-truth set (predictor training data + judge anchors)…")
    resp = call("POST", "/ground-truth-sets", corpus)
    print(f"      stored '{resp['name']}': {resp['usable']} usable records"
          + (f"  WARNINGS: {resp['warnings']}" if resp.get("warnings") else ""))

    print("\n[2/3] Evaluating every corpus artifact — recording what each rung predicts…")
    for r in records:
        job = call("POST", "/evaluate", {"artifact_id": r["artifact_ref"], "text": r["text"]})
        for _ in range(120):
            st = call("GET", f"/jobs/{job['job_id']}")
            if st["status"] not in ("queued", "running"):
                break
            time.sleep(0.3)
        if st["status"] != "done":
            print(f"      {r['artifact_ref']}: {st['status']} ({st.get('error')})")
            continue
        v = call("GET", f"/verdict/{st['verdict_id']}")
        shown = f"score {v['score']:.3f}" if v["score"] is not None else \
                ("eliminated" if v["eliminated"] else "gate-only")
        print(f"      {r['artifact_ref']:<24} true ctr {r['outcomes']['ctr']:.3f}  ->  {shown}")

    print("\n[3/3] Revealing the known outcomes — the harness measures each rung's correlation…")
    resp = call("POST", "/ground-truth", {"records": records})
    for rec in resp["recalibrated"]:
        print(f"      {rec['rung']:<24} Spearman r = {rec['spearman']:+.2f}  (n={rec['n']})")
    if not resp["recalibrated"]:
        print("      nothing recalibrated — were the evaluations in step 2 completed?")

    print("\nDone. Every rung now has a measured calibration record; the next artifact you")
    print("ingest gets a calibration-WEIGHTED verdict. Open the dashboard's Calibration view.")


if __name__ == "__main__":
    main()
