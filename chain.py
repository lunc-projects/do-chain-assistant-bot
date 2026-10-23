"""Live DO Chain data — endpoints verified 2026-10-23 via the do-chain.com portal proxy LCD + CoinGecko.
Standalone: generic public chain data only, no project-specific info."""
import base64, json, os, urllib.parse
import httpx
LCD = "https://do-chain.com/lcd"
RPC = "https://do-chain.com/rpc"
CHAIN_ID = "Do-Chain"
DENOM = "udo"          # staking token: DO, 6 decimals
GOV_DENOM = "udodx"    # governance token: DODx, 6 decimals
DECIMALS = 6
COINGECKO_ID = "lunc-cookie-do-coin"
PORTAL = "https://do-chain.com"

async def _get(path):
    async with httpx.AsyncClient(timeout=25, proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
        r = await c.get(f"{LCD}{path}"); r.raise_for_status(); return r.json()

async def prices():
    async with httpx.AsyncClient(timeout=25, proxy=os.getenv('OUTBOUND_PROXY') or None) as c:
        r = await c.get(f"https://api.coingecko.com/api/v3/simple/price?ids={COINGECKO_ID}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true")
        r.raise_for_status(); return r.json()

def fmt_price(d, name):
    vol = d.get('usd_24h_vol', 0)
    note = ""
    if vol and vol < 10000:
        note = ("\n   ⚠️ Very thin market — 24h trading volume is tiny, so this price can swing wildly "
                "and may not be what you'd actually get on the DEX. Treat it as a rough guide only.")
    return (f"{name}: ${d['usd']:.8g} ({d.get('usd_24h_change',0):+.2f}% 24h)\n"
            f"   Market cap: ${d.get('usd_market_cap',0):,.0f} | 24h volume: ${vol:,.0f}{note}")

async def stats_text():
    block = await _get("/cosmos/base/tendermint/v1beta1/blocks/latest")
    height = block["block"]["header"]["height"]
    supply = await _get(f"/cosmos/bank/v1beta1/supply/by_denom?denom={DENOM}")
    total = int(supply["amount"]["amount"]) / 10**DECIMALS
    pool = await _get("/cosmos/staking/v1beta1/pool")
    bonded = int(pool["pool"]["bonded_tokens"]) / 10**DECIMALS
    pct = bonded / total * 100 if total else 0
    return (f"📊 *DO Chain — live*\nBlock height: {height}\n"
            f"Total DO supply: {total:,.0f}\nBonded (staked): {bonded:,.0f} DO ({pct:.1f}% of supply)\n"
            f"Source: do-chain.com/lcd (DO Chain LCD)")

async def gov_tally_params():
    """DO Chain's own governance rules — read live, never assume another chain's.
    Verified 2026-10-23: quorum 0, threshold 0.5, veto_threshold 1.0."""
    d = await _get("/cosmos/gov/v1/params/tallying")
    tp = d.get("tally_params") or d.get("params", {})
    return tp

async def proposals_voting():
    d = await _get("/cosmos/gov/v1/proposals?proposal_status=2&pagination.limit=50")
    return d.get("proposals", [])

async def proposal_detail(pid):
    d = await _get(f"/cosmos/gov/v1/proposals/{pid}")
    return d["proposal"]

async def proposal_tally(pid):
    d = await _get(f"/cosmos/gov/v1/proposals/{pid}/tally")
    return d["tally"]

def tally_text(t):
    y, a, n, v = (int(t[k]) / 10**DECIMALS for k in ("yes_count", "abstain_count", "no_count", "no_with_veto_count"))
    total = y + a + n + v
    non_abstain = y + n + v
    if total == 0: return "No votes yet."
    def pc(x, base): return f"{x/base*100:.1f}%" if base else "—"
    return (f"YES {y:,.0f} ({pc(y, non_abstain)} of non-abstain)\nNO {n:,.0f}\n"
            f"NO WITH VETO {v:,.0f} ({pc(v, non_abstain)})\nABSTAIN {a:,.0f}\nTotal voted: {total:,.0f} DO\n"
            f"DO Chain rule: no quorum — a proposal passes if YES is over 50% of non-abstain votes when voting ends.")

# Friendly names for the denoms a wallet is most likely to hold
DENOM_NAMES = {"udo": "DO", "udodx": "DODx"}

async def wallet_text(addr):
    if not (addr.startswith("do1") and len(addr) >= 39):
        return "That doesn't look like a DO Chain address (do1…)."
    bal = await _get(f"/cosmos/bank/v1beta1/balances/{addr}")
    lines = ["💼 *Wallet* (public on-chain data)"]
    if not bal.get("balances"): lines.append("Balances: 0 / no balances found")
    for b in bal.get("balances", []):
        denom = DENOM_NAMES.get(b["denom"], b["denom"])
        amt = int(b["amount"]) / 10**DECIMALS
        lines.append(f"{denom}: {amt:,.6f}".rstrip("0").rstrip(".") if amt < 1 else f"{denom}: {amt:,.2f}")
    try:
        dels = await _get(f"/cosmos/staking/v1beta1/delegations/{addr}")
        tot = 0.0; rows = []
        for d in dels.get("delegation_responses", []):
            amt = int(d["balance"]["amount"]) / 10**DECIMALS; tot += amt
            rows.append((d["delegation"]["validator_address"], amt))
        if rows:
            lines.append(f"\nStaked total: {tot:,.2f} DO across {len(rows)} validator(s)")
            for va, amt in rows[:10]: lines.append(f"• {va[:20]}… : {amt:,.2f}")
    except Exception: pass
    lines.append(f"\nFull history: {PORTAL}")
    lines.append("🔒 Public data only — never share a seed phrase with anyone, this bot will never ask.")
    return "\n".join(lines)

async def token_text(arg):
    """Token info for a denom (udo, udodx, DO, DODx, ibc/…) or a CW20-style contract address.
    DO Chain's bank denom-metadata endpoint is not implemented, so denom info comes from live supply."""
    raw = arg.strip()
    low = raw.lower()
    if low in ("do", "dodx"):
        raw = DENOM if low == "do" else GOV_DENOM
    if raw.startswith("do1") and len(raw) >= 39:
        q = base64.b64encode(json.dumps({"token_info": {}}).encode()).decode()
        try:
            d = await _get(f"/cosmwasm/wasm/v1/contract/{raw}/smart/{q}")
            info = d["data"]
        except Exception:
            return "Couldn't read that contract — check it's a token contract address on DO Chain."
        dec = int(info["decimals"]); supply = int(info["total_supply"]) / (10 ** dec)
        return (f"🪙 *{info['name']} ({info['symbol']})*\nDecimals: {dec}\nTotal supply: {supply:,.2f} {info['symbol']}\n"
                f"Contract: {raw}\n{PORTAL}\n"
                f"⚠️ Token info is on-chain data only — it does NOT verify a token is safe or legitimate. Always DYOR.")
    # Denom path (native or IBC) — the LCD returns amount 0 for unknown denoms rather than an error
    try:
        d = await _get(f"/cosmos/bank/v1beta1/supply/by_denom?denom={urllib.parse.quote(raw, safe='')}")
        amt = int(d["amount"]["amount"]) / 10**DECIMALS
        if amt == 0 and raw not in DENOM_NAMES:
            return "Couldn't find that token on DO Chain — give me a denom (e.g. udo, udodx, ibc/…) or a token contract address."
    except Exception:
        return "Couldn't find that token on DO Chain — give me a denom (e.g. udo, udodx, ibc/…) or a token contract address."
    name = DENOM_NAMES.get(raw, raw)
    return (f"🪙 *{name}* (denom: {raw})\nDecimals: {DECIMALS}\nTotal supply: {amt:,.2f} {name}\n"
            f"Source: do-chain.com/lcd\n"
            f"⚠️ Supply is on-chain data only — it does NOT verify a token is safe or legitimate. Always DYOR.")

async def validator_by_addr(valoper):
    d = await _get(f"/cosmos/staking/v1beta1/validators/{valoper}")
    return d["validator"]

async def validators_top(limit=10):
    d = await _get(f"/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED&pagination.limit=200")
    vals = sorted(d.get("validators", []), key=lambda v: int(v["tokens"]), reverse=True)
    return vals[:limit]

def validator_text(v):
    rate = float(v["commission"]["commission_rates"]["rate"]) * 100
    tokens = int(v["tokens"]) / 10**DECIMALS
    return (f"*{v['description']['moniker']}*\nStatus: {v['status']} | Jailed: {v['jailed']}\n"
            f"Commission: {rate:.2f}% | Voting power (bonded): {tokens:,.0f} DO\n"
            f"Operator: {v['operator_address']}")

async def find_validator(query):
    """Search bonded+unbonded by moniker (case-insensitive substring) or exact valoper."""
    if query.startswith("dovaloper1"): return await validator_by_addr(query)
    out = []
    for status in ("BOND_STATUS_BONDED", "BOND_STATUS_UNBONDED", "BOND_STATUS_UNBONDING"):
        try:
            d = await _get(f"/cosmos/staking/v1beta1/validators?status={status}&pagination.limit=300")
            out += d.get("validators", [])
        except Exception: pass
    q = query.lower()
    return next((v for v in out if q in v["description"]["moniker"].lower()), None)

def snapshot(v):
    return {"status": v["status"], "jailed": v["jailed"],
            "commission": v["commission"]["commission_rates"]["rate"], "tokens": int(v["tokens"])}
