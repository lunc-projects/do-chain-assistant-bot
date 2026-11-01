#!/usr/bin/env python3
"""Offline tests for /topholders (owner direction 2026-11-01): the answer
must keep contract-held DO OUT of the people ranking — wallets in
👥 TOP 10, pairs under 💧, staking under 🥩, unidentified contracts only
in the full list's 🏭 section — and every message must carry its
"as of" stamp. Plain asserts, no network, no Telegram.

Run: python3 test_topholders.py
Covers: topholders.render() sectioning + ordering + stamps,
render_full() (top-50 + 🏭 section + coverage note), missing-cache
message, _apply_events() transfer/mint/burn math, and a dry run of the
bot's on_topholders / on_topholders_callback handlers against the
shipped seed cache (fake Update/Context, replies captured).
"""
import asyncio, json, os, sys, tempfile

_tmp = tempfile.mkdtemp(prefix="dobot-topholders-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "messages.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import topholders

SUPPLY = str(1000 * 10**6)  # 1,000 DO in raw units

def entry(addr, raw, kind, label=None):
    return {"address": addr, "balance_raw": str(raw), "kind": kind, "label": label}

CACHE = {
    "terra_classic": {
        "as_of": "2026-11-01 20:00 UTC",
        "supply_raw": SUPPLY,
        "coverage": "test coverage note (terra)",
        "classified": (
            [entry(f"terra1wallet{i:02d}", (100 - i) * 10**6, "wallet") for i in range(12)]
            + [entry("terra1pair", 500 * 10**6, "liquidity", "DO/LUNC pair (Garuda DEX)"),
               entry("terra1stake", 400 * 10**6, "staking", "Garuda DO staking pool"),
               entry("terra1mystery", 450 * 10**6, "contract", "Contract (unidentified)")]
        ),
    },
    "do_chain": {
        "as_of": "2026-11-01 20:00 UTC",
        "supply_raw": SUPPLY,
        "coverage": "test coverage note (dochain)",
        "classified": (
            [entry("do1bigwallet", 900 * 10**6, "wallet"),
             entry("do1wallet2", 50 * 10**6, "wallet"),
             entry("do1bonded", 950 * 10**6, "staking", "Staking pool — all staked DO"),
             entry("do1module", 10 * 10**6, "module", "Chain module: oracle")]
        ),
    },
}

# --- render(): sectioning -------------------------------------------------
msg = topholders.render(CACHE)
assert "as of 2026-11-01 20:00 UTC" in msg
people = msg.split("👥 *TOP 10 HOLDERS*")[1].split("💧")[0]
assert "terra1pair" not in people and "terra1stake" not in people and "terra1mystery" not in people
assert "terra1wallet00" in people and "terra1wallet09" in people
assert "terra1wallet10" not in people, "top-10 cut must hold"
assert "💧 *LIQUIDITY POOLS*" in msg and "terra1pair" in msg.split("💧 *LIQUIDITY POOLS*")[1]
assert "🥩 *STAKING POOLS*" in msg and "terra1stake" in msg
assert "terra1mystery" not in msg, "unidentified contracts stay out of the short message"
# DO Chain bonded pool (bigger than every wallet) must NOT head the people list
dc_people = msg.split("DO Chain — native DO")[1].split("👥 *TOP 10 HOLDERS*")[1].split("🥩")[0]
assert "do1bigwallet" in dc_people and "do1bonded" not in dc_people
assert "do1bonded" in msg.split("🥩 *STAKING POOLS*")[-1]

# --- render_full(): everything + coverage --------------------------------
full = topholders.render_full(CACHE)
assert "test coverage note (terra)" in full and "test coverage note (dochain)" in full
assert "terra1wallet10" in full and "terra1wallet11" in full, "full list goes past the top 10"
assert "🏭 *OTHER CONTRACTS / CHAIN MODULES*" in full and "terra1mystery" in full and "do1module" in full

# --- missing cache ---------------------------------------------------------
assert "isn't ready yet" in topholders.render(None)
assert "isn't ready yet" in topholders.render_full(None)

# --- _apply_events() math ---------------------------------------------------
TOKEN = topholders.TOKEN
def wasm_tx(events):
    return {"logs": [{"events": [{"type": "wasm", "attributes":
        [{"key": k, "value": v} for k, v in ev.items()]} for ev in events]}]}
b = {}
topholders._apply_events(b, wasm_tx([{"_contract_address": TOKEN, "action": "transfer",
                                      "from": "a", "to": "b", "amount": "100"}]))
assert b == {"a": -100, "b": 100}, b
topholders._apply_events(b, wasm_tx([{"_contract_address": TOKEN, "action": "mint",
                                      "to": "a", "amount": "250"}]))
topholders._apply_events(b, wasm_tx([{"_contract_address": TOKEN, "action": "burn",
                                      "from": "b", "amount": "40"}]))
assert b == {"a": 150, "b": 60}, b
# events for a different contract are ignored
topholders._apply_events(b, wasm_tx([{"_contract_address": "terra1other", "action": "transfer",
                                      "from": "a", "to": "b", "amount": "999"}]))
assert b == {"a": 150, "b": 60}, b

# --- handler dry run against the shipped seed -------------------------------
import bot  # noqa: E402  (env DB_PATH already pointed at the temp dir)

seed_text = topholders.cached_text()
assert "Top DO holders" in seed_text and "as of" in seed_text
seed_full = topholders.cached_full_text()
assert "Full DO holders list" in seed_full

class FakeMessage:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kw):
        self.replies.append((text, kw))

class FakeUpdate:
    def __init__(self):
        self.message = FakeMessage()

class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

class FakeQuery:
    def __init__(self):
        self.message = type("M", (), {"chat": type("C", (), {"id": 42})()})()
    async def answer(self):
        pass

async def _dry():
    u = FakeUpdate()
    await bot.on_topholders(u, None)
    assert u.message.replies, "handler must reply"
    text, kw = u.message.replies[-1]
    assert "🏆" in text and "👥 *TOP 10 HOLDERS*" in text
    markup = kw.get("reply_markup")
    assert markup is not None, "the Full list button must be attached"
    btn = markup.inline_keyboard[0][0]
    assert btn.text == "📋 Full list" and btn.callback_data == "th:full"
    # callback path sends the full list as follow-up message(s)
    u2 = FakeUpdate()
    u2.callback_query = FakeQuery()
    ctx = type("Ctx", (), {"bot": FakeBot()})()
    await bot.on_topholders_callback(u2, ctx)
    assert ctx.bot.sent and ctx.bot.sent[0][0] == 42
    assert "Full DO holders list" in "".join(t for _, t in ctx.bot.sent)

asyncio.run(_dry())
assert "topholders" in bot.HELP and "/topholders" in bot.HELP
print("test_topholders: ALL PASS")
