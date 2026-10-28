#!/usr/bin/env python3
"""Offline tests for the DO bot's summary fixes (owner direction
2026-10-28): summaries are SHORTER (compact digest, capped line count)
and must NEVER carry @name tags — Telegram re-tags (pings) those
people. Plain asserts, no network, no Telegram.

Run: python3 test_summary.py
Covers: strip_mentions() (start-of-text/line, mid-sentence, multiple,
opening punctuation, short handles, emails untouched), basic_summary()
(plain display names instead of 'Name (@handle)', the line cap with
oldest lines dropped whole, link-heavy input), and the /summary +
/catchup send paths passing through the sanitizer.
"""
import asyncio, os, sys, tempfile

# Point the store at a throwaway DB BEFORE importing the bot.
_tmp = tempfile.mkdtemp(prefix="dobot-summary-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "messages.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store
import bot

passed = 0

def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")

print("== strip_mentions ==")
check(bot.strip_mentions("@alice hello") == "alice hello",
      "handle at start of text loses its @")
check(bot.strip_mentions("first line\n@alice again") == "first line\nalice again",
      "handle at start of a line loses its @")
check(bot.strip_mentions("ask @alice please") == "ask alice please",
      "handle mid-sentence loses its @")
check(bot.strip_mentions("@alice and @bob_99 agree") == "alice and bob_99 agree",
      "multiple handles in one text all stripped")
check(bot.strip_mentions("(@alice) said so") == "(alice) said so",
      "handle after opening punctuation stripped")
check(bot.strip_mentions("mail me at bob.smith@gmail.com") == "mail me at bob.smith@gmail.com",
      "email address is NOT mangled")
check(bot.strip_mentions("abc@defg stays") == "abc@defg stays",
      "@ glued to a word character is left alone")
check(bot.strip_mentions("@ab is too short") == "@ab is too short",
      "handles shorter than 3 chars are left alone")
check(bot.strip_mentions("no handles here") == "no handles here",
      "text without handles is unchanged")

print("== basic_summary: plain names, no tags ==")
rows = [
    {"user_name": "Alice (@alice)", "text": "hey @bob check this", "ts": 1},
    {"user_name": "Bob (@bobby)", "text": "on it, asking @alice now", "ts": 2},
]
out = bot.basic_summary(rows)
check("Alice" in out and "Bob" in out, "display names are shown")
check("@alice" not in out and "@bobby" not in out and "@bob" not in out,
      "no @handle survives in the summary body")
out_sent = bot.strip_mentions(out)  # what the send paths actually send
check("@" not in out_sent, "sanitized summary contains no @ at all")

print("== basic_summary: shorter (line cap) ==")
many = [{"user_name": f"User{i} (@user{i})", "text": f"message number {i}", "ts": i}
        for i in range(40)]
out = bot.basic_summary(many)
lines = out.split("\n")
check(len(lines) <= bot.SUMMARY_MAX_LINES,
      f"40 messages summarize to <= {bot.SUMMARY_MAX_LINES} lines (got {len(lines)})")
check("message number 39" in out, "the most recent message is kept")
check("message number 0" not in out, "the oldest sample lines are dropped whole")
check(all(not ln.startswith("• User") or ": message number" in ln for ln in lines),
      "no line is truncated mid-way")
out_d = bot.basic_summary(many, detailed=True)
check(len(out_d.split("\n")) <= bot.SUMMARY_MAX_LINES,
      "detailed summaries obey the same line cap")

linky = [{"user_name": "Lin (@lin)", "text": f"see https://example{i}.com/x", "ts": i}
         for i in range(12)]
out = bot.basic_summary(linky)
check(len(out.split("\n")) <= bot.SUMMARY_MAX_LINES,
      "link-heavy summaries still fit the line cap")

em = [{"user_name": "Em (@em)", "text": "reach me at em@example.com please", "ts": 1}]
out_sent = bot.strip_mentions(bot.basic_summary(em))
check("em@example.com" in out_sent, "an email inside a summary survives sanitizing")

print("== send paths pass through the sanitizer ==")
class _Msg:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kw):
        self.replies.append(text)

class _User:
    def __init__(self, uid, name="Alice"):
        self.id = uid
        self.full_name = name
        self.username = "alice"

class _Chat:
    def __init__(self, cid, ctype="supergroup"):
        self.id = cid
        self.type = ctype

class _Update:
    def __init__(self, uid, cid):
        self.effective_user = _User(uid)
        self.effective_chat = _Chat(cid)
        self.message = _Msg()

class _Ctx:
    args = []

store.log_message(-2001, 11, "Alice (@alice)", "hey @bob look at this", 1)
store.log_message(-2001, 12, "Bob (@bobby)", "sure @alice, doing it", 2)
store.log_message(-2001, 11, "Alice (@alice)", "thanks @bobby", 3)

upd = _Update(11, -2001)
asyncio.run(bot.on_summary(upd, _Ctx()))
sent = "\n".join(upd.message.replies)
check("Summarizing 3 messages" in sent, "/summary answered")
check("@alice" not in sent and "@bob" not in sent and "@bobby" not in sent,
      "/summary output carries no @ tags")
body = upd.message.replies[-1]
check(len(body.split("\n")) <= bot.SUMMARY_MAX_LINES,
      "/summary output fits the line cap")

upd = _Update(12, -2001)
asyncio.run(bot.on_catchup(upd, _Ctx()))
sent = "\n".join(upd.message.replies)
check("Catchup" in sent, "/catchup answered")
check("@alice" not in sent and "@bob" not in sent and "@bobby" not in sent,
      "/catchup output carries no @ tags")

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")).read()
check("out = strip_mentions(basic_summary(rows))" in _src,
      "the DM summary path sanitizes too (source guard)")

print(f"\nALL {passed} CHECKS PASSED")
