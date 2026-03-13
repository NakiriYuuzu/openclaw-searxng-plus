#!/usr/bin/env python3
"""
Benchmark script for OpenClaw Search Gateway.

Measures:
- Top-10 retrieval success rate (target >= 90%)
- Top-5 relevance hit rate (target >= 80%)
- P95 latency without content fetch (target < 4s)
- P95 latency with content fetch (documented)

Usage:
    uv run python benchmark/bench.py [--base-url URL] [--token TOKEN]
"""
import argparse
import json
import statistics
import sys
import time

import httpx

# Test queries with expected relevant domains (for relevance scoring)
TEST_SET = [
    {
        "q": "python list comprehension tutorial",
        "relevant_domains": ["docs.python.org", "realpython.com", "w3schools.com", "geeksforgeeks.org", "python.org"],
    },
    {
        "q": "how to use git rebase",
        "relevant_domains": ["git-scm.com", "github.com", "atlassian.com", "stackoverflow.com"],
    },
    {
        "q": "rust programming language features",
        "relevant_domains": ["rust-lang.org", "doc.rust-lang.org", "wikipedia.org", "github.com"],
    },
    {
        "q": "docker compose networking explained",
        "relevant_domains": ["docs.docker.com", "docker.com", "stackoverflow.com", "github.com", "medium.com", "accesto.com", "netmaker.io", "digitalocean.com"],
    },
    {
        "q": "machine learning gradient descent",
        "relevant_domains": ["wikipedia.org", "towardsdatascience.com", "scikit-learn.org", "arxiv.org", "ibm.com", "google.com", "developers.google.com", "medium.com", "mit.edu"],
    },
    {
        "q": "react hooks useEffect cleanup",
        "relevant_domains": ["react.dev", "reactjs.org", "stackoverflow.com", "developer.mozilla.org", "medium.com", "freecodecamp.org", "dev.to"],
    },
    {
        "q": "kubernetes pod scheduling",
        "relevant_domains": ["kubernetes.io", "cloud.google.com", "docs.aws.amazon.com", "stackoverflow.com", "cncf.io", "medium.com", "cloudbolt.io"],
    },
    {
        "q": "postgresql index optimization",
        "relevant_domains": ["postgresql.org", "stackoverflow.com", "pganalyze.com", "github.com", "wikipedia.org", "medium.com", "pgtutorial.com", "citusdata.com"],
    },
    {
        "q": "nginx reverse proxy configuration",
        "relevant_domains": ["nginx.org", "nginx.com", "digitalocean.com", "stackoverflow.com", "medium.com", "linuxize.com", "ubuntu.com"],
    },
    {
        "q": "typescript generic constraints",
        "relevant_domains": ["typescriptlang.org", "stackoverflow.com", "developer.mozilla.org", "github.com", "medium.com", "dev.to", "digitalocean.com"],
    },
    {
        "q": "linux file permissions chmod",
        "relevant_domains": ["man7.org", "linux.die.net", "gnu.org", "stackoverflow.com", "wikipedia.org", "linuxize.com", "ubuntu.com", "digitalocean.com", "geeksforgeeks.org"],
    },
    {
        "q": "graphql vs rest api comparison",
        "relevant_domains": ["graphql.org", "apollographql.com", "stackoverflow.com", "wikipedia.org", "aws.amazon.com", "ibm.com", "medium.com", "hygraph.com", "postman.com"],
    },
    {
        "q": "css flexbox layout guide",
        "relevant_domains": ["developer.mozilla.org", "css-tricks.com", "w3schools.com", "flexboxfroggy.com", "medium.com", "freecodecamp.org"],
    },
    {
        "q": "redis caching strategies",
        "relevant_domains": ["redis.io", "redis.com", "stackoverflow.com", "aws.amazon.com", "medium.com", "digitalocean.com"],
    },
    {
        "q": "oauth2 authorization code flow",
        "relevant_domains": ["oauth.net", "auth0.com", "developer.okta.com", "rfc-editor.org", "stackoverflow.com", "medium.com", "digitalocean.com"],
    },
    {
        "q": "websocket protocol explained",
        "relevant_domains": ["developer.mozilla.org", "wikipedia.org", "rfc-editor.org", "stackoverflow.com", "medium.com", "ably.com", "ibm.com"],
    },
    {
        "q": "terraform aws vpc module",
        "relevant_domains": ["terraform.io", "registry.terraform.io", "github.com", "aws.amazon.com", "hashicorp.com", "medium.com"],
    },
    {
        "q": "pandas dataframe merge join",
        "relevant_domains": ["pandas.pydata.org", "stackoverflow.com", "realpython.com", "geeksforgeeks.org", "medium.com", "w3schools.com"],
    },
    {
        "q": "golang concurrency goroutines",
        "relevant_domains": ["go.dev", "golang.org", "gobyexample.com", "stackoverflow.com", "medium.com", "dev.to", "digitalocean.com"],
    },
    {
        "q": "jwt token authentication best practices",
        "relevant_domains": ["jwt.io", "auth0.com", "stackoverflow.com", "owasp.org", "medium.com", "descope.com", "loginradius.com", "logrocket.com", "reddit.com"],
    },
]


def run_query(client: httpx.Client, base_url: str, token: str, query: dict, need_content: bool = False):
    """Run a single search query and return timing + results."""
    payload = {
        "q": query["q"],
        "topK": 10,
        "needContent": need_content,
        "freshness": "any",
    }
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


def check_relevance(results: list[dict], relevant_domains: list[str], top_k: int = 5) -> bool:
    """Check if at least one of the top-K results is from a relevant domain."""
    for result in results[:top_k]:
        url = result.get("url", "").lower()
        for domain in relevant_domains:
            if domain in url:
                return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Benchmark OpenClaw Search Gateway")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Gateway base URL")
    parser.add_argument("--token", default="changeme", help="Auth token")
    parser.add_argument("--with-content", action="store_true", help="Also test with needContent=true")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    print(f"=== OpenClaw Search Gateway Benchmark ===")
    print(f"Target: {args.base_url}")
    print(f"Queries: {len(TEST_SET)}")
    print()

    client = httpx.Client()

    # --- Phase 1: Search without content ---
    print("Phase 1: Search (needContent=false)")
    print("-" * 50)

    retrieval_success = 0
    relevance_hits = 0
    latencies = []
    failures = []

    for i, query in enumerate(TEST_SET):
        result = run_query(client, args.base_url, args.token, query, need_content=False)
        status = "OK" if result["success"] else "FAIL"

        if result["success"]:
            n_results = len(result["results"])
            latency = result["timing_ms"]
            latencies.append(latency)

            if n_results > 0:
                retrieval_success += 1

            relevant = check_relevance(result["results"], query["relevant_domains"])
            if relevant:
                relevance_hits += 1

            print(f"  [{i+1:2d}/{len(TEST_SET)}] {status} | {n_results:2d} results | {latency:7.1f}ms | relevant={relevant} | {query['q'][:50]}")
        else:
            failures.append({"query": query["q"], "error": result.get("error")})
            print(f"  [{i+1:2d}/{len(TEST_SET)}] {status} | {result.get('error', 'unknown')} | {query['q'][:50]}")

        # Small delay to avoid hammering
        time.sleep(0.5)

    # --- Results ---
    total = len(TEST_SET)
    retrieval_rate = retrieval_success / total * 100 if total > 0 else 0
    relevance_rate = relevance_hits / total * 100 if total > 0 else 0

    print()
    print("=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"  Retrieval success (Top-10 >= 1 result): {retrieval_success}/{total} ({retrieval_rate:.1f}%) {'PASS' if retrieval_rate >= 90 else 'FAIL'} (target >= 90%)")
    print(f"  Relevance hit rate (Top-5 relevant):    {relevance_hits}/{total} ({relevance_rate:.1f}%) {'PASS' if relevance_rate >= 80 else 'FAIL'} (target >= 80%)")

    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p95_idx = min(int(len(latencies_sorted) * 0.95), len(latencies_sorted) - 1)
        p95 = latencies_sorted[p95_idx]
        avg = statistics.mean(latencies)
        print(f"  Latency P50:  {p50:.1f}ms")
        print(f"  Latency P95:  {p95:.1f}ms {'PASS' if p95 < 4000 else 'FAIL'} (target < 4000ms)")
        print(f"  Latency Avg:  {avg:.1f}ms")

    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures:
            print(f"    - {f['query']}: {f['error']}")

    # --- Phase 2: Content fetch (optional) ---
    if args.with_content:
        print()
        print("Phase 2: Search with content fetch (needContent=true)")
        print("-" * 50)
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
            cp95_idx = min(int(len(content_sorted) * 0.95), len(content_sorted) - 1)
            print(f"\n  Content fetch P50: {content_sorted[len(content_sorted)//2]:.1f}ms")
            print(f"  Content fetch P95: {content_sorted[cp95_idx]:.1f}ms")

    # --- Save results ---
    report = {
        "total_queries": total,
        "retrieval_success": retrieval_success,
        "retrieval_rate_pct": round(retrieval_rate, 1),
        "relevance_hits": relevance_hits,
        "relevance_rate_pct": round(relevance_rate, 1),
        "latency_p50_ms": round(latencies_sorted[len(latencies_sorted) // 2], 1) if latencies else None,
        "latency_p95_ms": round(p95, 1) if latencies else None,
        "latency_avg_ms": round(avg, 1) if latencies else None,
        "failures": failures,
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nResults saved to {args.output}")

    client.close()

    # Exit with error if targets not met
    if retrieval_rate < 90 or relevance_rate < 80:
        sys.exit(1)


if __name__ == "__main__":
    main()
