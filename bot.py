#!/usr/bin/env python3
"""DO Chain Assistant Bot — full AI assistant for Telegram groups.
Core: summarize hundreds of messages into a quick summary.
Also: /catchup, /tldr, /ask (general AI Q&A), DM summary. Standalone — DO Chain only, no other projects included.
Run: TELEGRAM_BOT_TOKEN=... AI_API_KEY=... python bot.py
"""
import os, re, time, json, datetime, pathlib
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import store, ai_client, chain, budget
from kb import kb_as_text, find_kb_answer

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)
LCD = "https://do-chain.com/lcd"

HELP = """🤖 *DO Chain Assistant Bot*

*Summaries (main job)*
/summary — last 200 messages
/summary 300 — last 300 messages
/summary 24h / /summary today / /summary 1h
/summary detailed — longer version
/catchup — what you missed since your last /catchup
/tldr — reply to a long message to shrink it

*Ask me*
/ask <question> — ask me anything
Or just @mention me in the group, or DM me

*Games*
/games — open DO Games (10 cookie games + regular leaderboard)

*Live info*
/price — DO price, market cap, volume
/stats — supply, block height, staking %
/convert <amount> DO — convert DO <-> USD
/proposals — all proposals currently voting
/proposal <id> — proposal detail + live tally
/wallet do1... — public wallet balance + staking
/token <denom or contract> — token info (e.g. /token udo, /token udodx)
/validators — top 10 validators by voting power
/validator <name or dovaloper1...> — validator detail

*Staking help*
/stake — how staking works, step by step
/calc <amount> — staking reward ESTIMATE

*Info*
/links — official links only
/safety — scam / seed phrase safety rules
/learn <word> — plain-English glossary (e.g. /learn quorum)

*Daily AI pot*
200,000 tokens a day (the free-plan allowance). When the pot runs out, AI pauses with a "daily limit reached" note until midnight UTC — simple commands and basic summaries keep working.

*Notifications (your choice, on/off)*
/govalerts — proposal / voting notifications menu (new, ending soon, result)
/watchvalidator <name or dovaloper1...> — watch a validator in this chat
/unwatchvalidator <dovaloper1...> — stop watching
/watchlist — validators watched in this chat
/settings — notification menus hub
In a group, only admins can change group settings. In DM, it's just for you.

*Other*
/help — this list
In DM: forward / paste any long text and I'll summarize it.
"""

def parse_summary_args(args, chat_id):
    detailed = "detailed" in args
    args = [a for a in args if a != "detailed"]
    now = int(time.time())
    if not args:
        return store.get_messages(chat_id, limit=200), detailed
    a = args[0].lower()
    if a in ("today",): return store.get_messages(chat_id, limit=1000, since_ts=now - (now % 86400)), detailed
    if a.endswith("h"):
        try: return store.get_messages(chat_id, limit=1000, since_ts=now - int(a[:-1])*3600), detailed
        except: pass
    if a.endswith("d"):
        try: return store.get_messages(chat_id, limit=1000, since_ts=now - int(a[:-1])*86400), detailed
        except: pass
    try: return store.get_messages(chat_id, limit=int(a)), detailed
    except: return store.get_messages(chat_id, limit=200), detailed

async def send_long(update, text):
    for i in range(0, len(text), 3900):
        await update.message.reply_text(text[i:i+3900])

async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)

GAMES_URL = "https://do-games-phi.vercel.app"

async def on_games(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat is not None and chat.type == "private":
        button = InlineKeyboardButton("🎮 Play DO Games", web_app=WebAppInfo(url=GAMES_URL))
    else:
        button = InlineKeyboardButton("🎮 Play DO Games", url=GAMES_URL)
    await update.message.reply_text("*DO Games* — 10 cookie games with one regular leaderboard. Your best run in each game adds up. Weekly and all-time boards; bragging rights only.", reply_markup=InlineKeyboardMarkup([[button]]), parse_mode=ParseMode.MARKDOWN)

async def on_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows, detailed = parse_summary_args(ctx.args, update.effective_chat.id)
    if not rows:
        await update.message.reply_text("No messages logged yet — I can only summarize messages sent after I joined this group. Give it some activity, then try /summary again.")
        return
    await update.message.reply_text(f"Summarizing {len(rows)} messages…")
    out = await ai_client.summarize(rows, detailed=detailed)
    await send_long(update, out)
    store.set_catchup(update.effective_chat.id, update.effective_user.id)

async def on_catchup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid, uid = update.effective_chat.id, update.effective_user.id
    last = store.get_catchup_id(cid, uid)
    if last is None:
        rows = store.get_messages(cid, limit=200)
        await update.message.reply_text("First catchup — here's the last 200, and I'll track from here next time.")
    else:
        rows = store.get_messages(cid, limit=1000, after_id=last)
    if not rows:
        await update.message.reply_text("You're all caught up — no new messages since your last /catchup.")
        return
    out = await ai_client.summarize(rows)
    await send_long(update, f"📬 Catchup — {len(rows)} new messages\n\n{out}")
    store.set_catchup(cid, uid)

async def on_tldr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message.reply_to_message
    if not msg or not msg.text:
        await update.message.reply_text("Reply to a long message with /tldr and I'll shrink it.")
        return
    out = await ai_client.chat([
        {"role":"system","content":"Summarize the message in 2-3 short lines. No extra commentary."},
        {"role":"user","content": msg.text}])
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else msg.text[:400]
    await update.message.reply_text(f"⚡ TL;DR: {out}")

async def on_ask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args).strip()
    if not q:
        await update.message.reply_text("Ask me something: /ask explain this proposal in simple words")
        return
    kb_hit = find_kb_answer(q)
    if kb_hit:
        await send_long(update, kb_hit)
        return
    out = await ai_client.chat([
        {"role":"system","content":"You are DO Chain Assistant Bot, a standalone AI assistant for DO Chain Telegram groups. Answer clearly and concisely. Do not invent contract addresses or prices. Knowledge base:\n" + kb_as_text()},
        {"role":"user","content": q}])
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "AI isn't configured yet (no AI_API_KEY). The owner can add the key in Railway and I'll answer fully."
    await send_long(update, out)


async def _can_change(update, ctx):
    chat = update.effective_chat
    if chat.type == "private": return True
    try:
        m = await ctx.bot.get_chat_member(chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

# ================= TOP PACK: live info =================
async def on_price2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        d = await chain.prices()
        msg = "💰 *Price — live (CoinGecko)*\n" + chain.fmt_price(d[chain.COINGECKO_ID], "DO (Lunc Cookie Do Coin)")
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("Couldn't fetch prices right now.")

async def on_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try: await update.message.reply_text(await chain.stats_text(), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch chain stats right now.")

async def on_convert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /convert 1000000  (DO amount)  or  /convert 10 usd"); return
    try:
        amt = float(ctx.args[0].replace(",", "")); d = await chain.prices(); price = d[chain.COINGECKO_ID]["usd"]
        if len(ctx.args) > 1 and ctx.args[1].lower() == "usd":
            await update.message.reply_text(f"${amt:,.2f} ≈ {amt/price:,.0f} DO (at ${price:.8g}, CoinGecko — thin market, rough guide only)")
        else:
            await update.message.reply_text(f"{amt:,.0f} DO ≈ ${amt*price:,.6f} (at ${price:.8g}, CoinGecko — thin market, rough guide only)")
    except Exception: await update.message.reply_text("Couldn't convert right now — check the amount format.")

async def on_proposals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        props = await chain.proposals_voting()
    except Exception:
        await update.message.reply_text("Couldn't fetch proposals right now."); return
    if not props:
        await update.message.reply_text("No proposals are in the voting period right now."); return
    lines = ["🗳️ *Proposals currently voting:*"]
    for pr in props:
        lines.append(f"\n*{pr['id']}* — {pr.get('title','(no title)')}\nVoting ends: {pr.get('voting_end_time','')} UTC\nUse /proposal {pr['id']} for the tally")
    await send_long(update, "\n".join(lines))

async def on_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /wallet do1..."); return
    try: await update.message.reply_text(await chain.wallet_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch that wallet right now.")

async def on_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /token udo — or /token udodx, an ibc/... denom, or a token contract address"); return
    await update.message.reply_text(await chain.token_text(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)

async def on_validators(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        vals = await chain.validators_top(10)
        lines = ["🏛️ *Top 10 validators by voting power*"]
        for i, v in enumerate(vals, 1):
            lines.append(f"{i}. {v['description']['moniker']} — {int(v['tokens'])/1e6:,.0f} DO, commission {float(v['commission']['commission_rates']['rate'])*100:.1f}%")
        lines.append("\nDetail: /validator <name>   Watch one: /watchvalidator <name>")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch validators right now.")

async def on_validator_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /validator <moniker or dovaloper1...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.message.reply_text("Validator not found — check the name or use the dovaloper1 address."); return
        await update.message.reply_text(chain.validator_text(v), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't fetch that validator right now.")

STAKE_TEXT = """🥩 *How DO staking works*
1. Hold DO in a wallet you control (DO Wallet — do-wallet.com, or a Cosmos wallet like Keplr with DO Chain added).
2. Pick a validator — check commission, uptime, and voting record (/validators). Smaller validators help decentralisation.
3. Delegate (stake) your DO to them. You can split across validators.
4. You earn rewards in DO; claim them in your wallet app. Governance deposits are a separate token (DODx) — staking is DO only.
5. Unbonding takes *21 days* — during that time DO earns nothing and can't move.
6. Redelegating moves stake to another validator instantly (then a 21-day cooldown for that amount).
Risks: validator downtime/slashing can cost a small %; price can move while unbonding — and DO's market is thin, so prices can move a lot. This is info, not financial advice."""

async def on_stake(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(STAKE_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_calc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /calc 1000000 — reward estimate for staking that many DO for 1 year"); return
    try:
        amt = float(ctx.args[0].replace(",", ""))
        # Estimate only: present a simple scenario table instead of a fake precise APR.
        lines = [f"🧮 *Reward ESTIMATE for {amt:,.0f} DO over 1 year* (before validator commission, not a promise):"]
        for apr in (5, 10, 15, 20):
            lines.append(f"• At {apr}% APR: ~{amt*apr/100:,.0f} DO")
        lines.append("Actual APR moves with staking ratio and commission — check your wallet app for the live rate before staking.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Check the amount — example: /calc 1000000")

LINKS_TEXT = """🔗 *Official links only*
DO Chain portal / explorer: https://do-chain.com
DEX: https://do-dex.com
DO Wallet: https://do-wallet.com
Keplr wallet: https://www.keplr.app
X: https://x.com/DoChainOfficial
Telegram community: https://t.me/cookiemunity
CoinGecko DO: https://www.coingecko.com/en/coins/lunc-cookie-do-coin
⚠️ Bookmark these. Scam copies of all of them exist — never trust a link DM'd to you."""

SAFETY_TEXT = """🛡️ *Safety rules*
• NEVER share your seed phrase / private key. No admin, validator, or bot will ever ask. This bot never will.
• Admins never DM you first with airdrops, support, or wallet fixes.
• Verify every contract / wallet address on the DO Chain portal (do-chain.com) before sending.
• A token being listed or named in chat is NOT verification it's safe.
• Bridging via IBC? Start with a small test amount — vouchers are claims on locked assets, not the originals.
• Use a fresh wallet for experiments; keep main funds separate.
• If it's urgent and guaranteed profit, it's a scam."""

GLOSSARY = {
 "quorum": "Minimum share of total voting power that must vote for a proposal result to count. DO Chain has NO quorum (it's set to 0) — a result counts no matter how few vote.",
 "veto": "NO WITH VETO: normally a strong rejection that also burns the deposit. On DO Chain the veto threshold is set to 100% of non-abstain votes, so a veto rejection is practically unreachable.",
 "unbonding": "After you unstake, DO is locked for 21 days — no rewards, can't transfer — then returns to your wallet.",
 "cw20": "A token standard for smart-contract tokens on Cosmos chains (like ERC-20). Many DO Chain tokens are native or IBC denoms instead — check with /token.",
 "validator": "Node operator who produces blocks and votes on governance. Delegators stake DO to them and share rewards minus commission.",
 "delegation": "Staking DO to a validator. Your DO stays yours; the validator can't spend it, but downtime/slashing can cost a small %.",
 "tally": "The live vote count on a proposal: YES / NO / NO WITH VETO / ABSTAIN, weighted by staked DO.",
 "ibc": "Inter-Blockchain Communication — how assets move between Cosmos chains. Assets are locked on the source chain and a voucher is issued on the other side. Ask me 'what is ibc' for the full explainer.",
 "dodx": "DODx is DO Chain's governance token (denom udodx). Proposal deposits are paid in DODx (minimum 1 DODx). Staking uses DO.",
}

async def on_links(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(LINKS_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_safety(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(SAFETY_TEXT, parse_mode=ParseMode.MARKDOWN)

async def on_learn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /learn <word> — try: " + ", ".join(GLOSSARY.keys())); return
    w = " ".join(ctx.args).lower()
    if w in GLOSSARY: await update.message.reply_text(f"📖 *{w}*: {GLOSSARY[w]}", parse_mode=ParseMode.MARKDOWN); return
    out = await ai_client.chat([{"role":"system","content":"Explain the crypto/DO Chain term in 2-3 plain lines for a beginner. No financial advice."},{"role":"user","content":w}])
    if not out:
        out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "I don't have that one yet — try /learn quorum"
    await update.message.reply_text(out)

# ================= GOV ALERTS (voting + proposals) =================
def gov_keyboard(chat_id):
    s = store.gov_settings(chat_id)
    def lbl(key, name): return f"{chr(9989) if s[key]=='on' else chr(10060)} {name}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl("gov_alerts", "Proposal alerts (master)"), callback_data="gov:gov_alerts")],
        [InlineKeyboardButton(lbl("gov_new", "New proposal voting"), callback_data="gov:gov_new"),
         InlineKeyboardButton(lbl("gov_ending", "Ending <24h"), callback_data="gov:gov_ending")],
        [InlineKeyboardButton(lbl("gov_result", "Final result"), callback_data="gov:gov_result")],
    ])

def gov_status_text(chat_id):
    s = store.gov_settings(chat_id)
    return (f"🗳️ *Proposal / voting notifications: {'ON' if s['gov_alerts']=='on' else 'OFF'}* for this chat\n"
            f"Tap to turn on/off. Types only fire when the master switch is ON.\n"
            f"• New proposal enters voting: {s['gov_new']}\n• Voting ending in <24h: {s['gov_ending']}\n• Final result (passed/rejected): {s['gov_result']}")

async def on_govalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if ctx.args and ctx.args[0].lower() in ("on", "off"):
        if not await _can_change(update, ctx):
            await update.message.reply_text("Only group admins can change this group's settings."); return
        store.set_setting(cid, "gov_alerts", ctx.args[0].lower())
    await update.message.reply_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_gov_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await _can_change(update, ctx):
        await q.answer("Only group admins can change group settings.", show_alert=True); return
    key = q.data.split(":", 1)[1]; cid = q.message.chat.id
    cur = store.get_setting(cid, key); store.set_setting(cid, key, "off" if cur == "on" else "on")
    await q.answer(f"{key}: {'OFF' if cur=='on' else 'ON'}")
    await q.edit_message_text(gov_status_text(cid), reply_markup=gov_keyboard(cid), parse_mode=ParseMode.MARKDOWN)

async def on_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ *Settings — notifications are your choice*\n🗳️ /govalerts — proposal & voting notifications\n🏛️ /watchlist — validators watched in this chat", parse_mode=ParseMode.MARKDOWN)

# ================= VALIDATOR WATCH =================
async def on_watchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /watchvalidator <moniker or dovaloper1...>"); return
    try:
        v = await chain.find_validator(" ".join(ctx.args))
        if not v: await update.message.reply_text("Validator not found."); return
        store.watch_validator(update.effective_chat.id, v["operator_address"], v["description"]["moniker"], json.dumps(chain.snapshot(v)))
        await update.message.reply_text(f"👀 Watching *{v['description']['moniker']}* in this chat.\nI'll alert here if it gets jailed, changes status or commission, or its voting power moves >5%.", parse_mode=ParseMode.MARKDOWN)
    except Exception: await update.message.reply_text("Couldn't add that validator right now.")

async def on_unwatchvalidator(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await update.message.reply_text("Usage: /unwatchvalidator <dovaloper1...> (see /watchlist)"); return
    n = store.unwatch_validator(update.effective_chat.id, ctx.args[0])
    await update.message.reply_text("Stopped watching that validator in this chat." if n else "That validator isn't on this chat's watchlist.")

async def on_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = store.list_watched(update.effective_chat.id)
    if not rows: await update.message.reply_text("No validators watched in this chat yet. Add one: /watchvalidator <name>"); return
    lines = ["👀 *Watched in this chat:*"] + [f"• {r['moniker']} — {r['valoper']}" for r in rows]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ================= WATCH JOBS =================
async def job_gov_check(ctx: ContextTypes.DEFAULT_TYPE):
    try: props = await chain.proposals_voting()
    except Exception: return
    seen_raw = store.get_setting(0, "gov_seen_voting") or ""
    seen = set(x for x in seen_raw.split(",") if x)
    tracked_raw = store.get_setting(0, "gov_tracked") or "{}"
    try: tracked = json.loads(tracked_raw)
    except Exception: tracked = {}
    chats = store.chats_with_gov_on(); now = datetime.datetime.now(datetime.timezone.utc)
    for pr in props:
        pid = str(pr["id"]); tracked[pid] = pr.get("status", "PROPOSAL_STATUS_VOTING_PERIOD")
        if pid not in seen:
            seen.add(pid)
            for cid in chats:
                if store.get_setting(cid, "gov_new") == "on":
                    try: await ctx.bot.send_message(cid, f"🗳️ New proposal in voting: *{pid} — {pr.get('title','')}*\nVoting ends: {pr.get('voting_end_time','')} UTC\nDetail: /proposal {pid}", parse_mode=ParseMode.MARKDOWN)
                    except Exception: pass
        # ending soon (<24h), once per proposal
        end_key = f"gov_ending_sent_{pid}"
        try:
            end = datetime.datetime.fromisoformat(pr["voting_end_time"].replace("Z", "+00:00"))
            if datetime.timedelta(0) < (end - now) < datetime.timedelta(hours=24) and not store.get_setting(0, end_key):
                store.set_setting(0, end_key, "1")
                for cid in chats:
                    if store.get_setting(cid, "gov_ending") == "on":
                        try: await ctx.bot.send_message(cid, f"⏰ Voting ends in <24h: *{pid} — {pr.get('title','')}*\nEnds: {pr['voting_end_time']} UTC\nUse /proposal {pid} for the live tally", parse_mode=ParseMode.MARKDOWN)
                        except Exception: pass
        except Exception: pass
    # results: tracked proposals no longer in voting list -> fetch final status once
    voting_ids = {str(pr["id"]) for pr in props}
    for pid in list(tracked.keys()):
        if pid not in voting_ids:
            try:
                final = await chain.proposal_detail(pid); status = final.get("status", "")
            except Exception: continue
            del tracked[pid]
            for cid in chats:
                if store.get_setting(cid, "gov_result") == "on":
                    try: await ctx.bot.send_message(cid, f"🗳️ Proposal *{pid}* finished: *{status}*\n{final.get('title','')}", parse_mode=ParseMode.MARKDOWN)
                    except Exception: pass
    store.set_setting(0, "gov_seen_voting", ",".join(sorted(seen)))
    store.set_setting(0, "gov_tracked", json.dumps(tracked))

async def job_validator_check(ctx: ContextTypes.DEFAULT_TYPE):
    by_val = {}
    for r in store.list_watched(): by_val.setdefault(r["valoper"], []).append(r)
    for valoper, rows in by_val.items():
        try: v = await chain.validator_by_addr(valoper)
        except Exception: continue
        new = chain.snapshot(v)
        for r in rows:
            try: old = json.loads(r["snapshot"])
            except Exception: old = {}
            alerts = []
            if old.get("jailed") != new["jailed"]: alerts.append(f"jailed changed: {old.get('jailed')} → {new['jailed']}")
            if old.get("status") != new["status"]: alerts.append(f"status changed: {old.get('status')} → {new['status']}")
            if old.get("commission") != new["commission"]: alerts.append(f"commission changed: {float(old.get('commission',0))*100:.2f}% → {float(new['commission'])*100:.2f}%")
            if old.get("tokens") and abs(new["tokens"] - old["tokens"]) / old["tokens"] > 0.05:
                alerts.append(f"voting power moved {(new['tokens']-old['tokens'])/old['tokens']*100:+.1f}% → {new['tokens']/1e6:,.0f} DO")
            if alerts:
                try: await ctx.bot.send_message(r["chat_id"], f"🏛️ Validator watch — *{r['moniker']}*\n" + "\n".join("• " + a for a in alerts), parse_mode=ParseMode.MARKDOWN)
                except Exception: pass
            store.update_snapshot(r["chat_id"], valoper, json.dumps(new))

async def on_proposal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /proposal <id> — see /proposals for what's voting"); return
    pid = ctx.args[0]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{LCD}/cosmos/gov/v1/proposals/{pid}"); r.raise_for_status()
            p = r.json()["proposal"]
        extra = ""
        try:
            tally = await chain.proposal_tally(pid); extra = "\n\n" + chain.tally_text(tally)
        except Exception: pass
        await send_long(update, f"🗳️ Proposal {pid}: {p.get('title','')}\nStatus: {p.get('status')}\nVoting ends: {p.get('voting_end_time')} UTC{extra}")
    except Exception as e:
        await update.message.reply_text(f"Couldn't fetch proposal {pid} right now.")

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat, user, text = update.effective_chat, update.effective_user, update.message.text
    name = user.full_name + (f" (@{user.username})" if user.username else "")
    # Log group messages for summaries
    if chat.type in ("group", "supergroup"):
        store.log_message(chat.id, user.id, name, text, update.message.message_id)
    # Mention = ask
    bot_name = (await ctx.bot.get_me()).username
    if bot_name and f"@{bot_name}" in text:
        q = text.replace(f"@{bot_name}", "").strip()
        if q:
            kb_hit = find_kb_answer(q)
            if kb_hit:
                await send_long(update, kb_hit)
                return
            out = await ai_client.chat([
                {"role":"system","content":"You are DO Chain Assistant Bot, a standalone AI assistant for DO Chain Telegram groups. Answer clearly and concisely. Knowledge base:\n" + kb_as_text()},
                {"role":"user","content": q}])
            if not out:
                out = ai_client.DAILY_LIMIT_NOTE if budget.exhausted() else "AI isn't configured yet (no AI_API_KEY)."
            await send_long(update, out)
        return
    # DM: any long text = summarize it
    if chat.type == "private" and len(text) > 600 and not text.startswith("/"):
        rows = [{"user_name": name, "text": text, "ts": int(time.time())}]
        out = await ai_client.summarize(rows)
        await send_long(update, out)

async def post_init(app: Application):
    try:
        await app.bot.set_my_description("DO Chain Assistant Bot — I summarize busy group chats into a quick TL;DR and answer DO Chain questions. Use /summary, /catchup, /ask in a group, or DM me a long text to summarize.")
        await app.bot.set_my_short_description("Summarizes hundreds of group messages into a quick summary + DO Chain assistant.")
        await app.bot.set_my_commands([
            ("summary","Summarize group messages"),("catchup","What you missed"),("tldr","Shrink a message (reply to it)"),
            ("ask","Ask me anything"),("games","Play DO Games (10 games)"),("proposals","Proposals voting now"),("proposal","Proposal + tally"),("price","DO price"),("stats","Chain stats"),("convert","Convert DO <-> USD"),("govalerts","Proposal alerts on/off"),("wallet","Public wallet lookup"),("token","Token info"),("validators","Top validators"),("watchvalidator","Watch a validator"),("help","All commands")])
        # Profile photo (owner's logo) — re-applied on boot so redeploys never lose it
        try:
            from telegram import InputFile, InputProfilePhotoStatic
            _pf = pathlib.Path(__file__).with_name("bot-profile-512.png")
            if _pf.exists():
                with open(_pf, "rb") as fh:
                    await app.bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=InputFile(fh.read(), filename="logo.png")))
        except Exception as e:
            print(f"profile photo: {e}")
        print("DO Chain Assistant Bot: description + commands set")
    except Exception as e:
        print(f"post_init: {e}")

def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing — paste it in Railway env vars (never in chat/repo).")
    _builder = Application.builder().token(TOKEN).post_init(post_init)
    _proxy = os.getenv("OUTBOUND_PROXY")
    if _proxy: _builder = _builder.proxy(_proxy).get_updates_proxy(_proxy)
    app = _builder.build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("help", on_start))
    app.add_handler(CommandHandler("summary", on_summary))
    app.add_handler(CommandHandler("catchup", on_catchup))
    app.add_handler(CommandHandler("tldr", on_tldr))
    app.add_handler(CommandHandler("ask", on_ask))
    app.add_handler(CommandHandler("games", on_games))
    app.add_handler(CommandHandler("proposal", on_proposal))
    app.add_handler(CommandHandler("price", on_price2))
    app.add_handler(CommandHandler("stats", on_stats))
    app.add_handler(CommandHandler("convert", on_convert))
    app.add_handler(CommandHandler("proposals", on_proposals))
    app.add_handler(CommandHandler("wallet", on_wallet))
    app.add_handler(CommandHandler("token", on_token))
    app.add_handler(CommandHandler("validators", on_validators))
    app.add_handler(CommandHandler("validator", on_validator_info))
    app.add_handler(CommandHandler("stake", on_stake))
    app.add_handler(CommandHandler("calc", on_calc))
    app.add_handler(CommandHandler("links", on_links))
    app.add_handler(CommandHandler("safety", on_safety))
    app.add_handler(CommandHandler("learn", on_learn))
    app.add_handler(CommandHandler("govalerts", on_govalerts))
    app.add_handler(CommandHandler("watchvalidator", on_watchvalidator))
    app.add_handler(CommandHandler("unwatchvalidator", on_unwatchvalidator))
    app.add_handler(CommandHandler("watchlist", on_watchlist))
    app.add_handler(CommandHandler("settings", on_settings))
    app.add_handler(CallbackQueryHandler(on_gov_callback, pattern=r"^gov:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    if app.job_queue:
        app.job_queue.run_repeating(job_gov_check, interval=1800, first=180)
        app.job_queue.run_repeating(job_validator_check, interval=3600, first=240)
    print("DO Chain Assistant Bot polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
