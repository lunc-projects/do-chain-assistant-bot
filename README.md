# DO Chain Assistant Bot

Full AI assistant for Telegram groups on DO Chain. Main job: turn hundreds of group messages into a quick summary.
Forked from the LUNC Assistant Bot (2026-10-23) and re-pointed at DO Chain only — separate bot, separate token, no LUNC content.

**Display name:** DO Chain Assistant Bot
**Username:** owner picks in BotFather (must end in `bot`)

## Commands
/summary, /summary 300, /summary 24h, /summary detailed, /catchup, /tldr (reply), /ask, /proposals, /proposal <id>, /price, /stats, /convert, /wallet do1..., /token <denom|contract>, /validators, /validator, /stake, /calc, /links, /safety, /learn, /govalerts, /watchvalidator, /watchlist, /settings, /help
DM the bot with a long pasted/forwarded text = instant summary.
Built-in knowledge base answers DO Chain questions (what DO/DODx are, governance rules, staking, wallets, DEX, IBC bridging — honest risks included).

## Chain facts (verified live 2026-10-23)
- LCD: https://do-chain.com/lcd · RPC: https://do-chain.com/rpc · chain-id `Do-Chain`
- Staking token DO: denom `udo`, 6 decimals, 21-day unbonding
- Governance token DODx: denom `udodx`, min proposal deposit 1 DODx
- Gov rules: quorum 0, threshold 50%, veto threshold 100% (read live by the bot, never assumed)
- Price source: CoinGecko `lunc-cookie-do-coin` — thin market (~$576/day volume at build time); /price carries a thin-liquidity warning

## Owner Setup — only 2 things only you can do
Bot creation and tokens live in your accounts; everything else is built here.

### 1. Create the bot in BotFather (2 minutes, in Telegram)
1. Open @BotFather > /newbot
2. Name: `DO Chain Assistant Bot`
3. Username: your choice ending in `bot`
4. BotFather gives you a token — DO NOT send it in chat or commit it. Keep it for the hosting step.
5. Then in BotFather: /mybots > your bot > Bot Settings > Group Privacy > **Turn off**
   (Or just make the bot Admin in your test group — that also lets it see messages. Doing both is best.)

### 2. Railway deploy (repo prepared, you paste secrets)
- New Railway project from this repo
- Variables: TELEGRAM_BOT_TOKEN (from BotFather), AI_API_KEY
  - Cheapest start: Groq free key at console.groq.com + AI_BASE_URL=https://api.groq.com/openai/v1 + AI_MODEL=openai/gpt-oss-120b
  - Or OpenAI key + defaults
- Start command is in Procfile: `python bot.py`

### 3. Test group
- Add bot to your test group, promote to Admin, send a few messages, then /summary

## Limits
- Bot only sees messages after it joins. No pre-join history via Bot API.
- Without AI_API_KEY it still works in fallback mode (stats/links/recent messages + the built-in KB), full AI summaries turn on when a key is added.
- Messages stored locally 7 days rolling (RETENTION_DAYS), only text/name/time.
- Bot does NOT report individual validator votes (public LCD votes endpoints are unreliable) — it never claims a validator did/didn't vote.
- No burn features: DO Chain has no burn tax. DO's market is thin — prices are labelled rough guides.

## Files
bot.py (main), chain.py (live DO Chain data), store.py (SQLite log + settings), ai_client.py (AI + fallback), kb.py (DO Chain knowledge base)

## Notifications (opt-in, default OFF)
- `/govalerts` tap-button menu: master ON/OFF + New proposal / Ending <24h / Final result. Job polls every 30 min.
- Validator watch: /watchvalidator <name|dovaloper1...> per chat, /unwatchvalidator, /watchlist. Hourly job alerts on jail, status, commission change, or voting-power move >5%. Generic — watch ANY validator, none pre-seeded.
