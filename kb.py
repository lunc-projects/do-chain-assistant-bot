"""Knowledge base — DO Chain facts, verified live on-chain 2026-10-23.
DO Chain Assistant Bot is a standalone project: DO Chain only, no other projects.
Answers here are informational only — no financial advice, no price promises.
"""

KB = {
    "what is do chain": (
        "DO Chain is its own sovereign Cosmos SDK blockchain (chain-id \"Do-Chain\") — a separate chain, "
        "not a token on another chain. It's built for DeFi and is IBC-connected, so assets can move between "
        "DO Chain and other Cosmos chains. Official site and explorer: https://do-chain.com"),
    "do token": (
        "DO is DO Chain's staking token (denom udo, 6 decimals). It's used to stake to validators, secure "
        "the network, and pay transaction fees. Live supply/staking numbers: /stats. Live price: /price — "
        "note the market is very thin, so prices move around a lot."),
    "dodx": (
        "DODx (denom udodx, 6 decimals) is DO Chain's governance token. Governance proposals need a deposit "
        "paid in DODx (minimum 1 DODx) before they can go to a vote. Staking is done in DO — see /stake."),
    "governance": (
        "DO Chain governance rules (read live from chain, different from many Cosmos chains): there is NO "
        "quorum — no minimum turnout. A proposal passes if YES is more than 50% of non-abstain votes when "
        "voting ends. The veto threshold is 100%, so a veto rejection is practically unreachable. Proposals "
        "need a deposit of at least 1 DODx to enter voting. See /proposals for what's live."),
    "staking": (
        "Staking on DO Chain: delegate DO to a validator with a wallet you control (DO Wallet or a Cosmos "
        "wallet like Keplr). You earn rewards in DO, minus the validator's commission (minimum 1% chain-wide). "
        "Unbonding takes 21 days — during that time the DO earns nothing and can't move. Redelegating to a "
        "different validator is instant, then that amount has a 21-day cooldown. Step by step: /stake"),
    "wallet": (
        "The official wallet is DO Wallet: https://do-wallet.com. Cosmos wallets such as Keplr "
        "(https://www.keplr.app) can also be used by adding the DO Chain network. NEVER share your seed "
        "phrase with anyone — no admin or bot will ever ask for it. More: /safety"),
    "dex": (
        "The DO Chain DEX is at https://do-dex.com — that's where DO and other DO Chain tokens trade. "
        "Liquidity is thin: check the actual pool depth before any swap, expect slippage on size, and "
        "start with a small test swap. Thin markets mean the price you see may not be the price you get."),
    "ibc": (
        "IBC (Inter-Blockchain Communication) is how assets move between Cosmos chains — for example moving "
        "LUNC from Terra Classic to DO Chain. How it works: the asset is locked on the source chain and a "
        "voucher version is issued on the destination chain; sending it back burns the voucher and unlocks "
        "the original. DO Chain's pitch to LUNC holders is trading on DO Chain without Terra Classic's on-chain "
        "tax — but be honest with yourself about the real costs and risks: bridging means trusting the relayers "
        "and both chains staying live, transfers can be slow or stuck if a relayer goes down, an IBC voucher is "
        "a claim on the locked asset (not the original in your wallet), and DO Chain markets are thin so getting "
        "back out at a fair price isn't guaranteed. Never bridge more than you can afford to have stuck."),
    "fees": (
        "DO Chain transaction fees are paid in DO. There is no burn tax on DO Chain — that point is often "
        "confused with Terra Classic, whose on-chain tax does not apply once assets are on DO Chain. You still "
        "pay normal transaction/DEX fees, and moving assets in or out via IBC has its own costs. See the "
        "\"ibc\" entry for the honest risks of bridging."),
    "explorer": (
        "The DO Chain portal is the network explorer: https://do-chain.com — network data, staking, "
        "governance, and your portfolio workspace."),
    "links": (
        "Official links: site/explorer https://do-chain.com · DEX https://do-dex.com · wallet "
        "https://do-wallet.com · X https://x.com/DoChainOfficial · Telegram community https://t.me/cookiemunity"),
}

# Aliases so common phrasings land on the right entry
_ALIASES = {
    "do chain": "what is do chain",
    "chain": "what is do chain",
    "do": "do token",
    "token": "do token",
    "gov": "governance",
    "voting": "governance",
    "proposal": "governance",
    "proposals": "governance",
    "stake": "staking",
    "delegate": "staking",
    "unbonding": "staking",
    "wallets": "wallet",
    "do wallet": "wallet",
    "keplr": "wallet",
    "swap": "dex",
    "trade": "dex",
    "bridge": "ibc",
    "bridging": "ibc",
    "move lunc": "ibc",
    "lunc": "ibc",
    "tax": "fees",
    "burn": "fees",
    "burn tax": "fees",
    "fee": "fees",
    "block explorer": "explorer",
}

def _normalise(q: str) -> str:
    return " ".join(q.lower().strip(" ?!.,").split())

def kb_as_text() -> str:
    lines = ["DO Chain knowledge base (verified 2026-10-23). Prefer these facts over general knowledge for DO Chain questions:"]
    for k, v in KB.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)

def find_kb_answer(q: str):
    n = _normalise(q)
    if n in KB:
        return KB[n]
    if n in _ALIASES:
        return KB[_ALIASES[n]]
    # loose match: any KB key fully contained in the question
    for k in KB:
        if k in n:
            return KB[k]
    for a, target in _ALIASES.items():
        if a in n:
            return KB[target]
    return None
