#!/usr/bin/env python3
"""
Benchmark script for OpenClaw Search Gateway.

Measures:
- Top-10 retrieval success rate (target >= 90%)
- Top-5 relevance hit rate (target >= 80%)
- P95 latency without content fetch (target < 4s)
- P95 latency with content fetch (documented)
- Per-language breakdown (en / zh-TW)

Usage:
    uv run python benchmark/bench.py [--base-url URL] [--token TOKEN]
    uv run python benchmark/bench.py --output improved.json --compare baseline.json
"""
import argparse
import json
import statistics
import sys
import time

import httpx

# Test queries with expected relevant domains (for relevance scoring)
TEST_SET = [
    # --- English queries ---
    {
        "q": "python list comprehension tutorial",
        "relevant_domains": ["docs.python.org", "realpython.com", "w3schools.com", "geeksforgeeks.org", "python.org"],
        "lang": "en",
    },
    {
        "q": "how to use git rebase",
        "relevant_domains": ["git-scm.com", "github.com", "atlassian.com", "stackoverflow.com"],
        "lang": "en",
    },
    {
        "q": "rust programming language features",
        "relevant_domains": ["rust-lang.org", "doc.rust-lang.org", "wikipedia.org", "github.com"],
        "lang": "en",
    },
    {
        "q": "docker compose networking explained",
        "relevant_domains": ["docs.docker.com", "docker.com", "stackoverflow.com", "github.com", "medium.com", "accesto.com", "netmaker.io", "digitalocean.com"],
        "lang": "en",
    },
    {
        "q": "machine learning gradient descent",
        "relevant_domains": ["wikipedia.org", "towardsdatascience.com", "scikit-learn.org", "arxiv.org", "ibm.com", "google.com", "developers.google.com", "medium.com", "mit.edu"],
        "lang": "en",
    },
    {
        "q": "react hooks useEffect cleanup",
        "relevant_domains": ["react.dev", "reactjs.org", "stackoverflow.com", "developer.mozilla.org", "medium.com", "freecodecamp.org", "dev.to"],
        "lang": "en",
    },
    {
        "q": "kubernetes pod scheduling",
        "relevant_domains": ["kubernetes.io", "cloud.google.com", "docs.aws.amazon.com", "stackoverflow.com", "cncf.io", "medium.com", "cloudbolt.io"],
        "lang": "en",
    },
    {
        "q": "postgresql index optimization",
        "relevant_domains": ["postgresql.org", "stackoverflow.com", "pganalyze.com", "github.com", "wikipedia.org", "medium.com", "pgtutorial.com", "citusdata.com"],
        "lang": "en",
    },
    {
        "q": "nginx reverse proxy configuration",
        "relevant_domains": ["nginx.org", "nginx.com", "digitalocean.com", "stackoverflow.com", "medium.com", "linuxize.com", "ubuntu.com"],
        "lang": "en",
    },
    {
        "q": "typescript generic constraints",
        "relevant_domains": ["typescriptlang.org", "stackoverflow.com", "developer.mozilla.org", "github.com", "medium.com", "dev.to", "digitalocean.com"],
        "lang": "en",
    },
    {
        "q": "linux file permissions chmod",
        "relevant_domains": ["man7.org", "linux.die.net", "gnu.org", "stackoverflow.com", "wikipedia.org", "linuxize.com", "ubuntu.com", "digitalocean.com", "geeksforgeeks.org"],
        "lang": "en",
    },
    {
        "q": "graphql vs rest api comparison",
        "relevant_domains": ["graphql.org", "apollographql.com", "stackoverflow.com", "wikipedia.org", "aws.amazon.com", "ibm.com", "medium.com", "hygraph.com", "postman.com"],
        "lang": "en",
    },
    {
        "q": "css flexbox layout guide",
        "relevant_domains": ["developer.mozilla.org", "css-tricks.com", "w3schools.com", "flexboxfroggy.com", "medium.com", "freecodecamp.org"],
        "lang": "en",
    },
    {
        "q": "redis caching strategies",
        "relevant_domains": ["redis.io", "redis.com", "stackoverflow.com", "aws.amazon.com", "medium.com", "digitalocean.com"],
        "lang": "en",
    },
    {
        "q": "oauth2 authorization code flow",
        "relevant_domains": ["oauth.net", "auth0.com", "developer.okta.com", "rfc-editor.org", "stackoverflow.com", "medium.com", "digitalocean.com"],
        "lang": "en",
    },
    {
        "q": "websocket protocol explained",
        "relevant_domains": ["developer.mozilla.org", "wikipedia.org", "rfc-editor.org", "stackoverflow.com", "medium.com", "ably.com", "ibm.com"],
        "lang": "en",
    },
    {
        "q": "terraform aws vpc module",
        "relevant_domains": ["terraform.io", "registry.terraform.io", "github.com", "aws.amazon.com", "hashicorp.com", "medium.com"],
        "lang": "en",
    },
    {
        "q": "pandas dataframe merge join",
        "relevant_domains": ["pandas.pydata.org", "stackoverflow.com", "realpython.com", "geeksforgeeks.org", "medium.com", "w3schools.com"],
        "lang": "en",
    },
    {
        "q": "golang concurrency goroutines",
        "relevant_domains": ["go.dev", "golang.org", "gobyexample.com", "stackoverflow.com", "medium.com", "dev.to", "digitalocean.com"],
        "lang": "en",
    },
    {
        "q": "jwt token authentication best practices",
        "relevant_domains": ["jwt.io", "auth0.com", "stackoverflow.com", "owasp.org", "medium.com", "descope.com", "loginradius.com", "logrocket.com", "reddit.com"],
        "lang": "en",
    },
    # --- zh-TW queries ---
    {
        "q": "台積電法說會",
        "relevant_domains": ["cnyes.com", "ctee.com.tw", "udn.com", "ltn.com.tw", "moneydj.com", "twse.com.tw", "chinatimes.com"],
        "lang": "zh-TW",
    },
    {
        "q": "Python 教學 入門",
        "relevant_domains": ["docs.python.org", "w3schools.com", "runoob.com", "ithelp.ithome.com.tw", "medium.com", "hackmd.io"],
        "lang": "zh-TW",
    },
    {
        "q": "台灣天氣預報",
        "relevant_domains": ["cwb.gov.tw", "cwa.gov.tw", "weather.com", "accuweather.com", ".gov.tw"],
        "lang": "zh-TW",
    },
    {
        "q": "健保卡報稅",
        "relevant_domains": [".gov.tw", "etax.nat.gov.tw", "nhi.gov.tw", "fia.gov.tw", "money.udn.com"],
        "lang": "zh-TW",
    },
    {
        "q": "台股走勢分析",
        "relevant_domains": ["cnyes.com", "goodinfo.tw", "histock.tw", "twse.com.tw", "cmoney.tw", "wantgoo.com", "moneydj.com", "ctee.com.tw"],
        "lang": "zh-TW",
    },
    {
        "q": "React 前端框架教學",
        "relevant_domains": ["react.dev", "reactjs.org", "ithelp.ithome.com.tw", "medium.com", "hackmd.io", "w3schools.com"],
        "lang": "zh-TW",
    },
    {
        "q": "台灣高鐵時刻表",
        "relevant_domains": ["thsrc.com.tw", ".gov.tw", "tw.yahoo.com", "google.com"],
        "lang": "zh-TW",
    },
    {
        "q": "Linux 伺服器架設教學",
        "relevant_domains": ["ithelp.ithome.com.tw", "blog.gtwang.org", "ubuntu.com", "linux.vbird.org", "medium.com", "digitalocean.com"],
        "lang": "zh-TW",
    },
    {
        "q": "TSMC 台積電 Q1 財報",
        "relevant_domains": ["cnyes.com", "ctee.com.tw", "udn.com", "moneydj.com", "twse.com.tw", "ltn.com.tw", "reuters.com"],
        "lang": "zh-TW",
    },
    {
        "q": "台灣美食推薦",
        "relevant_domains": ["ifoodie.tw", "klook.com", "tripadvisor.com", "travel.taipei", ".gov.tw", "kkday.com"],
        "lang": "zh-TW",
    },
]


def run_query(
    client: httpx.Client,
    base_url: str,
    token: str,
    query: dict,
    need_content: bool = False,
):
    """Run a single search query and return timing + results."""
    payload = {
        "q": query["q"],
        "topK": 10,
        "needContent": need_content,
        "freshness": "any",
    }
    if "lang" in query:
        payload["lang"] = query["lang"]

    start = time.time()
    try:
        resp = client.post(
            f"{base_url}/search",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        elapsed_ms = (time.time() - start) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "results": data["results"],
                "total_found": data["total_found"],
                "timing_ms": data["timing_ms"],
                "wall_ms": elapsed_ms,
            }
        return {"success": False, "error": f"HTTP {resp.status_code}", "wall_ms": elapsed_ms}
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000
        return {"success": False, "error": str(e), "wall_ms": elapsed_ms}


def _extract_domain(url: str) -> str:
    """Extract domain from URL for strict matching."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def check_relevance(results: list[dict], relevant_domains: list[str], top_k: int = 5) -> bool:
    """Check if at least one of the top-K results is from a relevant domain (strict matching)."""
    for result in results[:top_k]:
        host = _extract_domain(result.get("url", ""))
        if not host:
            continue
        for domain in relevant_domains:
            domain = domain.lower()
            if host == domain or host.endswith("." + domain):
                return True
    return False


def print_comparison(baseline_path: str, current_report: dict):
    """Print side-by-side comparison between baseline and current results."""
    try:
        with open(baseline_path) as f:
            baseline = json.load(f)
    except FileNotFoundError:
        print(f"\n  Warning: baseline file '{baseline_path}' not found, skipping comparison.")
        return

    print()
    print("=" * 60)
    print("COMPARISON (Baseline vs Improved)")
    print("=" * 60)
    header = f"  {'Metric':<30} {'Baseline':>10} {'Improved':>10} {'Delta':>10}"
    print(header)
    print("  " + "-" * 58)

    metrics = [
        ("Retrieval (en)", "retrieval_rate_en_pct", "retrieval_rate_en_pct"),
        ("Retrieval (zh-TW)", "retrieval_rate_zh_pct", "retrieval_rate_zh_pct"),
        ("Retrieval (all)", "retrieval_rate_pct", "retrieval_rate_pct"),
        ("Relevance (en)", "relevance_rate_en_pct", "relevance_rate_en_pct"),
        ("Relevance (zh-TW)", "relevance_rate_zh_pct", "relevance_rate_zh_pct"),
        ("Relevance (all)", "relevance_rate_pct", "relevance_rate_pct"),
        ("Latency P95", "latency_p95_ms", "latency_p95_ms"),
    ]

    for label, base_key, curr_key in metrics:
        base_val = baseline.get(base_key)
        curr_val = current_report.get(curr_key)

        base_str = f"{base_val:.1f}" if base_val is not None else "N/A"
        curr_str = f"{curr_val:.1f}" if curr_val is not None else "N/A"

        if base_val is not None and curr_val is not None:
            delta = curr_val - base_val
            sign = "+" if delta >= 0 else ""
            delta_str = f"{sign}{delta:.1f}"
        elif base_val is None and curr_val is not None:
            delta_str = "NEW"
        else:
            delta_str = "-"

        unit = "ms" if "latency" in label.lower() else "%"
        print(f"  {label:<30} {base_str + unit:>10} {curr_str + unit:>10} {delta_str:>10}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark OpenClaw Search Gateway")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Gateway base URL")
    parser.add_argument("--token", default="changeme", help="Auth token")
    parser.add_argument("--with-content", action="store_true", help="Also test with needContent=true")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    parser.add_argument("--compare", default=None, help="Compare with baseline JSON file")
    args = parser.parse_args()

    en_queries = [q for q in TEST_SET if q.get("lang", "en") == "en"]
    zh_queries = [q for q in TEST_SET if q.get("lang") == "zh-TW"]

    print("=== OpenClaw Search Gateway Benchmark ===")
    print(f"Target: {args.base_url}")
    print(f"Queries: {len(TEST_SET)} (en: {len(en_queries)}, zh-TW: {len(zh_queries)})")
    print()

    client = httpx.Client()

    # --- Warmup: discard first 3 queries to avoid cold-start bias ---
    print("Warmup (3 queries, results discarded)...")
    for query in TEST_SET[:3]:
        run_query(client, args.base_url, args.token, query, need_content=False)
        time.sleep(0.3)
    print()

    # --- Phase 1: Search without content ---
    print("Phase 1: Search (needContent=false)")
    print("-" * 60)

    # Per-language counters
    stats = {
        "en": {"retrieval": 0, "relevance": 0, "total": 0, "latencies": []},
        "zh-TW": {"retrieval": 0, "relevance": 0, "total": 0, "latencies": []},
    }
    failures = []

    for i, query in enumerate(TEST_SET):
        lang = query.get("lang", "en")
        result = run_query(client, args.base_url, args.token, query, need_content=False)
        status = "OK" if result["success"] else "FAIL"

        if result["success"]:
            n_results = len(result["results"])
            latency = result["timing_ms"]
            stats[lang]["latencies"].append(latency)
            stats[lang]["total"] += 1

            if n_results > 0:
                stats[lang]["retrieval"] += 1

            relevant = check_relevance(result["results"], query["relevant_domains"])
            if relevant:
                stats[lang]["relevance"] += 1

            print(f"  [{i+1:2d}/{len(TEST_SET)}] {status} [{lang:5s}] | {n_results:2d} results | {latency:7.1f}ms | relevant={relevant} | {query['q'][:45]}")
        else:
            stats[lang]["total"] += 1
            failures.append({"query": query["q"], "lang": lang, "error": result.get("error")})
            print(f"  [{i+1:2d}/{len(TEST_SET)}] {status} [{lang:5s}] | {result.get('error', 'unknown')} | {query['q'][:45]}")

        time.sleep(0.5)

    # --- Results ---
    all_latencies = stats["en"]["latencies"] + stats["zh-TW"]["latencies"]
    total = len(TEST_SET)
    total_retrieval = stats["en"]["retrieval"] + stats["zh-TW"]["retrieval"]
    total_relevance = stats["en"]["relevance"] + stats["zh-TW"]["relevance"]
    retrieval_rate = total_retrieval / total * 100 if total > 0 else 0
    relevance_rate = total_relevance / total * 100 if total > 0 else 0

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    for lang_key, label in [("en", "English"), ("zh-TW", "中文 (zh-TW)")]:
        s = stats[lang_key]
        t = s["total"]
        if t == 0:
            continue
        r_rate = s["retrieval"] / t * 100
        rel_rate = s["relevance"] / t * 100
        print(f"\n  [{label}] ({t} queries)")
        print(f"    Retrieval:  {s['retrieval']}/{t} ({r_rate:.1f}%) {'PASS' if r_rate >= 90 else 'FAIL'}")
        print(f"    Relevance:  {s['relevance']}/{t} ({rel_rate:.1f}%) {'PASS' if rel_rate >= 80 else 'FAIL'}")
        if s["latencies"]:
            lat_sorted = sorted(s["latencies"])
            p95_idx = int((len(lat_sorted) - 1) * 0.95)
            print(f"    Latency P50: {lat_sorted[len(lat_sorted)//2]:.1f}ms")
            print(f"    Latency P95: {lat_sorted[p95_idx]:.1f}ms")

    print(f"\n  [Overall] ({total} queries)")
    print(f"    Retrieval:  {total_retrieval}/{total} ({retrieval_rate:.1f}%) {'PASS' if retrieval_rate >= 90 else 'FAIL'} (target >= 90%)")
    print(f"    Relevance:  {total_relevance}/{total} ({relevance_rate:.1f}%) {'PASS' if relevance_rate >= 80 else 'FAIL'} (target >= 80%)")

    if all_latencies:
        latencies_sorted = sorted(all_latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95_idx = int((len(latencies_sorted) - 1) * 0.95)
        p95 = latencies_sorted[p95_idx]
        avg = statistics.mean(all_latencies)
        print(f"    Latency P50:  {p50:.1f}ms")
        print(f"    Latency P95:  {p95:.1f}ms {'PASS' if p95 < 5000 else 'FAIL'} (target < 5000ms)")
        print(f"    Latency Avg:  {avg:.1f}ms")

    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures:
            print(f"    - [{f['lang']}] {f['query']}: {f['error']}")

    # --- Phase 2: Content fetch (optional) ---
    if args.with_content:
        print()
        print("Phase 2: Search with content fetch (needContent=true)")
        print("-" * 60)
        content_latencies = []
        sample_queries = TEST_SET[:5]

        for i, query in enumerate(sample_queries):
            result = run_query(client, args.base_url, args.token, query, need_content=True)
            if result["success"]:
                latency = result["timing_ms"]
                content_latencies.append(latency)
                n_with_content = sum(1 for r in result["results"] if r.get("content"))
                n_partial = sum(1 for r in result["results"] if r.get("content_partial"))
                print(f"  [{i+1}/{len(sample_queries)}] {latency:7.1f}ms | {n_with_content} with content, {n_partial} partial | {query['q'][:40]}")
            else:
                print(f"  [{i+1}/{len(sample_queries)}] FAIL | {result.get('error')} | {query['q'][:40]}")
            time.sleep(1.0)

        if content_latencies:
            content_sorted = sorted(content_latencies)
            cp95_idx = int((len(content_sorted) - 1) * 0.95)
            print(f"\n  Content fetch P50: {content_sorted[len(content_sorted)//2]:.1f}ms")
            print(f"  Content fetch P95: {content_sorted[cp95_idx]:.1f}ms")

    # --- Build report ---
    en_s = stats["en"]
    zh_s = stats["zh-TW"]

    report = {
        "total_queries": total,
        "retrieval_success": total_retrieval,
        "retrieval_rate_pct": round(retrieval_rate, 1),
        "relevance_hits": total_relevance,
        "relevance_rate_pct": round(relevance_rate, 1),
        # Per-language
        "retrieval_rate_en_pct": round(en_s["retrieval"] / max(en_s["total"], 1) * 100, 1),
        "retrieval_rate_zh_pct": round(zh_s["retrieval"] / max(zh_s["total"], 1) * 100, 1),
        "relevance_rate_en_pct": round(en_s["relevance"] / max(en_s["total"], 1) * 100, 1),
        "relevance_rate_zh_pct": round(zh_s["relevance"] / max(zh_s["total"], 1) * 100, 1),
        # Latency
        "latency_p50_ms": round(latencies_sorted[len(latencies_sorted) // 2], 1) if all_latencies else None,
        "latency_p95_ms": round(p95, 1) if all_latencies else None,
        "latency_avg_ms": round(avg, 1) if all_latencies else None,
        "failures": failures,
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {args.output}")

    # --- Comparison ---
    if args.compare:
        print_comparison(args.compare, report)

    client.close()

    # Exit with error if targets not met
    if retrieval_rate < 90 or relevance_rate < 80:
        sys.exit(1)


if __name__ == "__main__":
    main()
