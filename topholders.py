"""Top-holders snapshot for /topholders — plain data, no AI.

Two chains:
• Terra Classic — the DO CW20 token. CW20 has no all-holders query, so
  balances are rebuilt from the token's full FCD transfer history once
  (the seed file), then kept current by an incremental FCD walk that
  only applies txs newer than the last processed height.
• DO Chain — native `udo`. The LCD auth module enumerates every
  account, so a refresh is an exact full re-enumeration whose sum is
  reconciled against total supply.

Display rule (owner's design): contract-held tokens are NEVER mixed
into the people ranking. Holders are classified as wallet / liquidity
(pair) / staking / contract (unidentified) / module, the classification
is stored in the cache, and the sections stay separate on every
refresh. Classification = known addresses first, then on-chain probes
(contract exists? pair query? staking config query?) — anything that
can't be identified is labelled a contract, never guessed a person.

The cache lives next to the bot DB (same /data volume as store.py).
Refresh runs hourly from bot.py's job queue; /topholders only reads
the cache, so it answers instantly and always shows its "as of" time.
"""
import asyncio, base64, json, os, time
import httpx

TOKEN = "terra15p8su45k45axng8ue59rl6zph4at27s49u3agr6uqrx3dhcxpg3qt0ekdt"  # DO on Terra Classic
FCD = "https://terra-classic-fcd.publicnode.com/v1/txs"
TC_LCD = "https://terra-classic-lcd.publicnode.com"
DO_LCD = "https://do-chain.com/lcd"
DEC = 6
CLASSIFY_N = 60   # classify this many top balances per chain

_DIR = os.path.dirname(os.getenv("DB_PATH", "data/messages.db")) or "data"
CACHE_PATH = os.path.join(_DIR, "topholders.json")
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topholders_seed.json")

# Known addresses: address -> (kind, label)
KNOWN_TC = {
    "terra1xvjwd55c4z932xu04npl296g8mmjhlzxy8rlvrkgwgnxve53w88q2mer37": ("staking", "Garuda DO staking pool (drained Oct 31, 2026)"),
    "terra1cf0fxnvhcmsqnw8levj3vrhrq3nxgfmc86w9d6pxyeghqyrkgj2spgqarl": ("liquidity", "DO/LUNC pair (Garuda DEX)"),
    "terra1ktlxt99d08x99wlds9p2j59uh6jy0nww7uq55l": ("wallet", "⚠️ drain wallet (Oct 31, 2026)"),
}
KNOWN_DC = {
    "bonded_tokens_pool": ("staking", "Staking pool — all staked DO"),
}

def _load_cache():
    for path in (CACHE_PATH, SEED_PATH):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            continue
    return None

def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_PATH)

def _amt_pct(raw, supply):
    return int(raw) / 10**DEC, (int(raw) / int(supply) * 100 if int(supply) else 0)

def _explorer_url(chain_key, addr):
    if chain_key == "terra_classic":
        return f"https://finder.terraclassic.community/mainnet/account/{addr}"
    return f"https://do-chain.com/wallet/{addr}"

def _addr_link(chain_key, addr):
    """Display = ONLY the last 4 characters, tappable to the full explorer page."""
    return f"[{addr[-4:]}]({_explorer_url(chain_key, addr)})"

def _short_label(label):
    """Compact label: any full address inside it shrinks to its last 4."""
    if not label:
        return ""
    import re
    return re.sub(r"(?:terra1|do1)[a-z0-9]{20,}", lambda m: "…" + m.group(0)[-4:], label)

def _section(chain_key, entries, kinds, supply, limit=None, numbered_from=1):
    rows = [e for e in entries if e["kind"] in kinds]
    if limit:
        rows = rows[:limit]
    out = []
    for i, e in enumerate(rows, numbered_from):
        amt, pct = _amt_pct(e["balance_raw"], supply)
        lbl = f" · {_short_label(e['label'])}" if e.get("label") else ""
        out.append(f"{i}. {_addr_link(chain_key, e['address'])} · {amt:,.0f} DO · {pct:.2f}%{lbl}")
    return out

def render(cache):
    """The /topholders message: top-10 people + pools + staking, per chain."""
    if not cache:
        return "Top holders snapshot isn't ready yet — try again in a bit."
    lines = ["🏆 *Top DO holders* — tap an address (last 4) for its explorer page"]
    for key, title in (("terra_classic", "Luna Classic — DO token (CW20)"),
                       ("do_chain", "DO Chain — native DO (udo)")):
        c = cache.get(key)
        if not c:
            continue
        lines.append(f"*{title}* · _as of {c['as_of']}_")
        lines.append("👥 *TOP 10 HOLDERS* (wallets only)")
        lines += _section(key, c["classified"], ("wallet",), c["supply_raw"], limit=10) or ["(none in snapshot)"]
        liq = _section(key, c["classified"], ("liquidity",), c["supply_raw"])
        if liq:
            lines.append("💧 *LIQUIDITY POOLS* (locked in pair contracts)")
            lines += liq
        stk = _section(key, c["classified"], ("staking",), c["supply_raw"])
        if stk:
            lines.append("🥩 *STAKING POOLS* (locked in staking contracts)")
            lines += stk
    lines.append("Contracts sit separately — locked in code, not a person's wallet. 📋 Full list = DM'd to you only.")
    return "\n".join(lines)

def render_full(cache):
    """The 📋 Full list follow-up: top-50 wallets + every contract section + coverage."""
    if not cache:
        return "Top holders snapshot isn't ready yet — try again in a bit."
    lines = ["📋 *Full DO holders list* — tap an address (last 4) for its explorer page"]
    for key, title in (("terra_classic", "Luna Classic — DO token (CW20)"),
                       ("do_chain", "DO Chain — native DO (udo)")):
        c = cache.get(key)
        if not c:
            continue
        lines.append(f"*{title}* · _as of {c['as_of']}_ · _{c['coverage']}_")
        lines.append("👥 *TOP 50 HOLDERS* (wallets only)")
        lines += _section(key, c["classified"], ("wallet",), c["supply_raw"], limit=50) or ["(none in snapshot)"]
        for kinds, head in ((("liquidity",), "💧 *LIQUIDITY POOLS*"),
                            (("staking",), "🥩 *STAKING POOLS*"),
                            (("contract", "module"), "🏭 *OTHER CONTRACTS / CHAIN MODULES* (unidentified — not counted as holders)")):
            rows = _section(key, c["classified"], kinds, c["supply_raw"])
            if rows:
                lines.append(head)
                lines += rows
    lines.append("On-chain data only — a big balance is not proof of who owns a wallet. DYOR.")
    return "\n".join(lines)

def cached_text():
    return render(_load_cache())

def cached_full_text():
    return render_full(_load_cache())

# ---------- classification probes ----------

async def _smart(client, lcd, addr, msg):
    q = base64.b64encode(json.dumps(msg).encode()).decode()
    r = await client.get(f"{lcd}/cosmwasm/wasm/v1/contract/{addr}/smart/{q}")
    if r.status_code != 200:
        return None
    return r.json().get("data")

async def _is_contract(client, lcd, addr):
    r = await client.get(f"{lcd}/cosmwasm/wasm/v1/contract/{addr}")
    return r.status_code == 200

async def _classify_tc(client, addr, known):
    if addr in KNOWN_TC:
        kind, label = KNOWN_TC[addr]
        return kind, label
    if addr in known:
        return known[addr]["kind"], known[addr]["label"]
    if not await _is_contract(client, TC_LCD, addr):
        return "wallet", None
    pair = await _smart(client, TC_LCD, addr, {"pair": {}})
    if pair:
        assets = pair.get("asset_infos") or []
        if any((a.get("token") or {}).get("contract_addr") == TOKEN for a in assets):
            return "liquidity", "Liquidity pair (holds DO)"
    cfg = await _smart(client, TC_LCD, addr, {"config": {}})
    if cfg and TOKEN in json.dumps(cfg):
        return "staking", "Staking contract (holds staked DO)"
    return "contract", "Contract (unidentified)"

async def _classify_dc(client, addr, module_name, known):
    if module_name:
        if module_name in KNOWN_DC:
            kind, label = KNOWN_DC[module_name]
            return kind, label
        return "module", f"Chain module: {module_name}"
    if addr in known:
        return known[addr]["kind"], known[addr]["label"]
    if not await _is_contract(client, DO_LCD, addr):
        return "wallet", None
    pair = await _smart(client, DO_LCD, addr, {"pair": {}})
    if pair:
        assets = pair.get("asset_infos") or []
        if any((a.get("native_token") or {}).get("denom") == "udo" for a in assets):
            return "liquidity", "Liquidity pair (holds DO)"
    # No loose staking rule: a config merely mentioning "udo" is not proof
    # a contract is a staking contract. Unproven = unidentified.
    return "contract", "Contract (unidentified)"

async def _classify_all(chain_key, client, ranked, module_names, old_classified):
    """Classify the top CLASSIFY_N balances of one chain, reusing prior results."""
    known = {e["address"]: e for e in (old_classified or [])}
    out = []
    for addr, raw in ranked[:CLASSIFY_N]:
        if chain_key == "terra_classic":
            kind, label = await _classify_tc(client, addr, known)
        else:
            kind, label = await _classify_dc(client, addr, module_names.get(addr), known)
        out.append({"address": addr, "balance_raw": str(raw), "kind": kind, "label": label})
    return out

# ---------- Terra Classic: incremental FCD walk ----------

def _apply_events(balances, tx):
    for log in tx.get("logs") or []:
        for ev in log.get("events", []):
            if ev.get("type") != "wasm":
                continue
            attrs = {}
            for a in ev.get("attributes", []):
                attrs.setdefault(a["key"], a["value"])
            if attrs.get("_contract_address") != TOKEN:
                continue
            action = attrs.get("action", "")
            try:
                amt = int(attrs.get("amount", "0"))
            except ValueError:
                continue
            frm, to = attrs.get("from"), attrs.get("to")
            if action in ("transfer", "transfer_from", "send", "send_from") and frm and to:
                balances[frm] = balances.get(frm, 0) - amt
                balances[to] = balances.get(to, 0) + amt
            elif action == "mint" and to:
                balances[to] = balances.get(to, 0) + amt
            elif action == "burn" and frm:
                balances[frm] = balances.get(frm, 0) - amt

async def _tc_token_supply(client):
    q = base64.b64encode(json.dumps({"token_info": {}}).encode()).decode()
    r = await client.get(f"{TC_LCD}/cosmwasm/wasm/v1/contract/{TOKEN}/smart/{q}")
    r.raise_for_status()
    return r.json()["data"]["total_supply"]

async def refresh_terra(cache):
    """Apply FCD txs newer than the snapshot's height to its balance map.
    Block tx sets are final once indexed, so a height watermark is exact."""
    tc = cache.get("terra_classic")
    if not tc or "balances" not in tc:
        return  # no seed state to advance — leave the shipped snapshot as-is
    balances = {k: int(v) for k, v in tc["balances"].items()}
    since = int(tc["as_of_height"])
    newest = since
    offset = None
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            url = f"{FCD}?account={TOKEN}&limit=100" + (f"&offset={offset}" if offset else "")
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            txs = d.get("txs", [])
            if not txs:
                break
            page_heights = [int(t.get("height", 0)) for t in txs]
            for tx in txs:
                h = int(tx.get("height", 0))
                if h > since:
                    _apply_events(balances, tx)
                    newest = max(newest, h)
            if max(page_heights) <= since:
                break
            offset = d.get("next")
            if not offset:
                break
        supply = await _tc_token_supply(client)
        pos = sorted(((a, b) for a, b in balances.items() if b > 0), key=lambda kv: -kv[1])
        classified = await _classify_all("terra_classic", client, pos, {}, tc.get("classified"))
    total = sum(b for _, b in pos)
    tc.update({
        "as_of": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "as_of_height": newest,
        "supply_raw": str(supply),
        "coverage": (f"balances rebuilt from the token's full on-chain transfer history; "
                     f"recomputed balances account for {total / int(supply) * 100:.2f}% of total supply"),
        "balances": {a: str(b) for a, b in balances.items() if b != 0},
        "classified": classified,
    })

# ---------- DO Chain: exact full enumeration ----------

async def refresh_dochain(cache):
    accounts, key = [], None
    module_names = {}
    async with httpx.AsyncClient(timeout=45) as client:
        while True:
            url = f"{DO_LCD}/cosmos/auth/v1beta1/accounts?pagination.limit=1000"
            if key:
                url += f"&pagination.key={key}"
            r = await client.get(url)
            r.raise_for_status()
            d = r.json()
            for acc in d.get("accounts", []):
                addr = acc.get("address") or (acc.get("base_account") or {}).get("address")
                if addr:
                    accounts.append(addr)
                    if acc.get("name"):
                        module_names[addr] = acc["name"]
            key = (d.get("pagination") or {}).get("next_key")
            if not key:
                break
        r = await client.get(f"{DO_LCD}/cosmos/bank/v1beta1/supply/by_denom?denom=udo")
        r.raise_for_status()
        supply = int(r.json()["amount"]["amount"])
        sem = asyncio.Semaphore(10)

        async def one(addr):
            async with sem:
                r = await client.get(f"{DO_LCD}/cosmos/bank/v1beta1/balances/{addr}/by_denom?denom=udo")
                r.raise_for_status()
                return addr, int((r.json().get("balance") or {}).get("amount", "0"))

        rows = await asyncio.gather(*(one(a) for a in accounts))
        rows.sort(key=lambda x: -x[1])
        old = (cache.get("do_chain") or {}).get("classified")
        classified = await _classify_all("do_chain", client, rows, module_names, old)
    total = sum(b for _, b in rows)
    cache["do_chain"] = {
        "as_of": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "supply_raw": str(supply),
        "coverage": (f"every account on chain checked ({len(accounts)} accounts); "
                     f"balances sum to {total / supply * 100:.2f}% of total supply"),
        "classified": classified,
    }

async def refresh():
    """Hourly job: advance both chains, then persist. Failures keep the old cache."""
    cache = _load_cache() or {}
    try:
        await refresh_terra(cache)
    except Exception as e:
        print(f"topholders: terra refresh failed: {e}")
    try:
        await refresh_dochain(cache)
    except Exception as e:
        print(f"topholders: dochain refresh failed: {e}")
    if cache:
        _save_cache(cache)
    return cache
