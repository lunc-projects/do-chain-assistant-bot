# BUILD NOTES — DO Chain Assistant Bot (built 2026-10-23)

Fork of `~/workspace/lunc-assistant-bot/` → `~/workspace/do-chain-assistant-bot/`. Source untouched (verified by checksum after the build).

## Files
- `bot.py` — main bot (514 lines, was 608)
- `chain.py` — rewritten for DO Chain
- `kb.py` — rewritten: DO Chain knowledge base (was intentionally empty in the LUNC bot)
- `store.py` — message log + settings (burn settings removed)
- `ai_client.py` — unchanged except bot identity strings
- `requirements.txt`, `Procfile`, `.env.example`, `.gitignore` — carried over unchanged
- `README.md` — rewritten for DO Chain
- **Not carried over:** `burn.py` (deleted), `bot-profile-512.png` (that's the LUNC bot's logo — owner sets this bot's own photo in BotFather)

## Stripped (all LUNC-specific content)
- burn.py module, /burn command, /burnalerts menu + callback, hourly burn-check job, daily burn report job, BIG_BURN_THRESHOLD env
- Burn alert settings in store.py (BURN_DEFAULTS, burn_settings, chats_with_burn_on)
- PublicNode LCD, terra1/terravaloper prefixes, uluna/uusd denoms, Finder links, LUNC/USTC prices, LUNC glossary (incl. the "burn tax" entry), LUNC stake text and /links

## Added / changed for DO Chain
- chain.py: LCD `https://do-chain.com/lcd`, RPC const, chain-id `Do-Chain`, denom `udo` / gov denom `udodx`, 6 decimals, CoinGecko id `lunc-cookie-do-coin`
- /price: DO only, with an automatic thin-market warning when 24h volume < $10K (fires at current ~$575/day)
- Gov: `gov_tally_params()` reads DO Chain's own tally params live; tally text states DO Chain's rule (no quorum, YES > 50% of non-abstain). Proposal deposits are DODx (in KB/stake text)
- /token: works by denom (udo, udodx, DO, DODx, ibc/…) via live supply — bank denom-metadata is **Not Implemented** on this LCD, so metadata lookup isn't possible; CW20-style contract query kept as the address path. Zero-supply unknown denoms report "couldn't find" (LCD returns 0 instead of an error)
- /wallet: do1… validation, DO/DODx friendly denom names, portal link is the do-chain.com root (deep-link route pattern not confirmed — matches spec's fallback)
- kb.py: real KB — what DO Chain is, DO vs DODx, governance rules, staking, wallets (DO Wallet, Keplr), DEX (thin liquidity warning), honest IBC explainer (lock/voucher mechanics, relayer risk, thin exit liquidity), fees (no burn tax on DO Chain). /ask and @mentions check the KB first, then fall back to AI with the KB in context
- Glossary: quorum/veto rewritten to DO Chain's actual params (quorum 0, veto threshold 100%), added ibc + dodx entries
- Kept unchanged by design: /summary /catchup /tldr /ask /learn mechanics, gov-alert + validator-watch design (opt-in, OFF by default, 30-min gov job / hourly validator job), all guardrails, env-var config (TELEGRAM_BOT_TOKEN, AI_API_KEY, AI_BASE_URL, AI_MODEL)

## Verification (2026-10-23, live LCD, read-only — bot never run against Telegram, no token used)
- `py_compile` clean on all 5 modules; all modules import in a venv with the pinned requirements
- Live function results:
  - prices: DO $5.6723e-10 (+17.79% 24h), market cap $207,837, 24h volume $575 → thin-market note shown
  - stats: block height 8,446,959; total supply 316,160,333,742,493 DO; bonded 81,613,005,976,351 DO (25.8%)
  - gov tally params (live): quorum 0.0, threshold 0.5, veto_threshold 1.0
  - proposals in voting: 0 (matches spec)
  - top validators: Do Foundation 19,736,683,287,533 DO (2.00% commission), Generation DO, Strata Labs; find_validator("Generation DO") → dovaloper1xjrjvd9nww0tnp3wj0q26te7awafkm90xzrz6k; snapshot() OK
  - wallet_text on a real account (from the chain's auth list): showed IBC denoms + DO: 82,119,510.21; a terra1… address correctly rejected
  - token_text: udo supply 316,160,333,742,493.19 DO; DODx supply 110,000.00; unknown denom → not-found message
  - tally_text (fabricated tally): percentages + DO Chain rule line correct
  - KB: correct hits for do chain / staking / ibc / burn tax / dex questions; nonsense → None
- store round-trips (gov settings, validator watch, message log, catchup) all passed against a temp DB
- Local-test quirk: this VM's `no_proxy` env contains bracketed IPv6 entries that crash httpx 0.27's env-proxy parsing; tests ran with a sanitised no_proxy. A Railway deploy won't have that env, and the LUNC bot has the identical behaviour — not a code change.

## Not verified / left open
- **Telegram end-to-end**: not run (no token, by instruction). Handler wiring was checked by import + code audit only.
- **/proposal detail/tally against a real proposal**: 0 proposals were in voting at build time, so proposal_detail/proposal_tally were only exercised via the proposals list call + tally_text formatting. Endpoints are the same gov/v1 shape the LUNC bot uses live.
- **CW20 path of /token**: no known CW20 token contract on DO Chain to test against; the code fails gracefully if wasm isn't enabled.
- **proposal messages field name**: DO Chain proposals weren't available to confirm whether new-style `title` or legacy fields are used; bot reads `title` like the LUNC bot (works on gov v1).
- Owner steps remaining: BotFather creation + username, token into Railway variables, profile photo, test group.
