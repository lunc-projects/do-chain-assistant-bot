#!/usr/bin/env python3
"""Offline tests for the DO bot's owner-only /botstats — plain asserts,
no network, no Telegram.

Run: python3 test_botstats.py
Covers: store.usage_counts() against a seeded throwaway DB, and the
on_botstats handler end-to-end (owner gets the card, non-owner gets
silence, no owner configured = silence for everyone). Also guards that
/botstats is registered as a handler but NOT in the public command list.
"""
import asyncio, os, sys, tempfile

# Point the store at a throwaway DB and set the owner BEFORE importing.
_tmp = tempfile.mkdtemp(prefix="dobot-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "messages.db")
os.environ["OWNER_TELEGRAM_ID"] = "606060"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store
import bot

passed = 0

def check(cond, label):
    global passed
    assert cond, f"FAILED: {label}"
    passed += 1
    print(f"  ok: {label}")

print("== usage_counts on an empty DB ==")
u = store.usage_counts()
check(u == {"groups": 0, "people_in_groups": 0, "dm_users": 0, "messages": 0},
      "empty DB counts are all zero")

print("== usage_counts on a seeded DB ==")
# One group (-1001), two distinct talkers (11 twice, 12 once)
store.log_message(-1001, 11, "Ann", "hello", 1)
store.log_message(-1001, 11, "Ann", "again", 2)
store.log_message(-1001, 12, "Bob", "hi all", 3)
# A second group (-1002), one talker
store.log_message(-1002, 13, "Cid", "yo", 4)
# One DM user via chat_settings, one via catchup
store.set_setting(555, "gov_alerts", "on")
store.set_catchup(556, 11)
u = store.usage_counts()
check(u["groups"] == 2, "two groups seen in the log")
check(u["people_in_groups"] == 3, "distinct group talkers counted once each")
check(u["dm_users"] == 2, "DM users counted from settings + catchup")
check(u["messages"] == 4, "all logged messages counted")

print("== /botstats handler ==")
class _Msg:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kw):
        self.replies.append(text)

class _User:
    def __init__(self, uid): self.id = uid

class _Update:
    def __init__(self, uid):
        self.effective_user = _User(uid)
        self.effective_message = _Msg()
        self.message = self.effective_message

class _Ctx:
    args = []

check(bot.OWNER_ID == 606060, "owner id picked up from env")
upd = _Update(606060)
asyncio.run(bot.on_botstats(upd, _Ctx()))
check(len(upd.effective_message.replies) == 1, "owner gets the /botstats card")
_txt = upd.effective_message.replies[0]
check("Groups I'm in and logging: 2" in _txt, "card shows the group count")
check("People seen talking in those groups: 3" in _txt, "card shows group talkers")
check("People who've used me in DM (settings/catchup): 2" in _txt, "card shows DM users")
check("Messages currently logged: 4" in _txt, "card shows the message count")
check("pot" not in _txt.lower(), "card has NO AI-pot line (this bot has no AI)")

upd = _Update(606061)
asyncio.run(bot.on_botstats(upd, _Ctx()))
check(upd.effective_message.replies == [], "non-owner gets silence")

_saved = bot.OWNER_ID
try:
    bot.OWNER_ID = 0
    upd = _Update(606060)
    asyncio.run(bot.on_botstats(upd, _Ctx()))
    check(upd.effective_message.replies == [], "no owner configured = silence for everyone")
finally:
    bot.OWNER_ID = _saved

print("== registration guards ==")
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.py")).read()
check('CommandHandler("botstats", on_botstats)' in _src, "botstats handler is registered")
_cmds = _src.split("set_my_commands([", 1)[1].split("])", 1)[0]
check("botstats" not in _cmds, "botstats is NOT in the public command list")
check("botstats" not in bot.HELP, "botstats is NOT in /help")

print(f"\nALL {passed} CHECKS PASSED")
