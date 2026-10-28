#!/usr/bin/env python3
"""Offline tests for stats_report (combined daily usage reporting):
payload shape, no-op when UPSTASH_STATS_* is unset, failure swallowing,
and current_counts() against a throwaway DB.

Run: python3 test_stats_report.py
"""
import asyncio, json, os, sys, tempfile, types

_tmp = tempfile.mkdtemp(prefix="do-stats-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "messages.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# httpx is a Railway-only dep on this VM; stub it — every publish call
# below injects a fake client factory, so no real HTTP ever happens.
_httpx = types.ModuleType("httpx")


class _NoRealHTTP:
    def __init__(self, *a, **k):
        raise AssertionError("real HTTP not allowed in tests")


_httpx.AsyncClient = _NoRealHTTP
sys.modules.setdefault("httpx", _httpx)

import stats_report
import store

passed = 0


def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"result": "OK"}


class FakeClient:
    def __init__(self, recorder, fail=False):
        self.recorder = recorder
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, content=None):
        self.recorder.append((url, headers, content))
        if self.fail:
            raise RuntimeError("network down")
        return FakeResp()


print("== no-op when unconfigured ==")
os.environ.pop("UPSTASH_STATS_URL", None)
os.environ.pop("UPSTASH_STATS_TOKEN", None)
check(stats_report.configured() is False, "unconfigured without env")
check(asyncio.run(stats_report.publish({"groups_logging": 1})) is False,
      "publish is a silent no-op when unset")

print("== publish writes the payload with a 3-day TTL ==")
os.environ["UPSTASH_STATS_URL"] = "https://stats.example.test/"
os.environ["UPSTASH_STATS_TOKEN"] = "tok123"
calls = []
ok = asyncio.run(stats_report.publish(
    {"groups_logging": 3, "people_in_groups": 7, "dm_users": 2, "messages_logged": 11},
    client_factory=lambda: FakeClient(calls)))
check(ok is True, "publish reports success")
check(len(calls) == 1, "exactly one HTTP call")
url, headers, content = calls[0]
check("/set/botstats%3Ado" in url and "EX=259200" in url,
      "SET botstats:do with EX=259200 (3 days)")
check(headers.get("Authorization") == "Bearer tok123", "bearer token header")
body = json.loads(content)
check(body["bot"] == "do" and isinstance(body["ts"], int), "payload carries bot + unix ts")
check(body["groups_logging"] == 3 and body["dm_users"] == 2, "payload carries the counts")
check("pot_spent" not in body, "no pot fields — this bot has no AI")

print("== failures are swallowed ==")
bad = []
check(asyncio.run(stats_report.publish({"groups_logging": 1},
                                       client_factory=lambda: FakeClient(bad, fail=True))) is False,
      "transport failure returns False, never raises")

print("== current_counts comes from usage_counts ==")
store.log_message(-1001, 11, "Ann", "hello", 1)
store.log_message(-1001, 12, "Bob", "hi", 2)
c = stats_report.current_counts()
check(c == {"groups_logging": 1, "people_in_groups": 2, "dm_users": 0, "messages_logged": 2},
      "counts match the seeded log")

print(f"\n{passed} checks passed")
