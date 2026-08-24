# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Also hosts a Python-based Multi-Chain Arbitrage Telegram Bot.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)
- **Python**: 3.11 (for Arb Bot)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally
- `python3 main.py` — run the Arb Bot directly

## Arb Bot (Solana only)

**Entry point:** `main.py`
**Modules:** `bot/` package
- `bot/config.py` — all constants, watchlist (25 SOL tokens), DEX mappings
- `bot/state.py` — persistent state manager (JSON, survives restarts)
- `bot/fetcher.py` — async DexScreener fetcher
- `bot/analyzer.py` — intra-chain gap detection + confidence scoring
- `bot/alerts.py` — Telegram message builders
- `bot/live_executor.py` — Jupiter quotes, pre-flight, live execution; global rate throttle (2s)
- `bot/telegram.py` — send + async command polling (full command suite)
- `bot/scanner.py` — main async scan loop

**Workflow:** `Arb Bot` (console, runs `python3 main.py`)

**Required secrets:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Features:**
- 25 SOL tokens monitored concurrently via async I/O (BSC removed)
- Intra-chain arb: finds price gaps across Solana DEXes
- Jupiter pre-flight validates every gap before alerting or trading
- Global Jupiter rate throttle (2s min interval) prevents 429s across all call paths
- Confidence scoring (0–100) per opportunity; min=40 to pass to pre-flight
- New pool detection alerts; persistent state survives restarts (bot/state.json)
- Full Telegram command suite: /add, /remove, /watchlist, /opportunities, /topgaps, /stats, /status, /config, /pause, /resume, /setspread, /settrade, /setcooldown, /setliquidity, /help

## Football Draw Bot

**Entry point:** `football_bot/main.py`
**Modules:** `football_bot/` package — completely separate from the Arb Bot

- `football_bot/config.py` — leagues, API settings, draw weights, schedule constants
- `football_bot/state.py` — persistent state (signals, grades, performance — `football_bot/state.json`)
- `football_bot/fetcher.py` — football-data.org v4 API (fixtures, team form, H2H, results)
- `football_bot/analyzer.py` — 5-factor draw + home/away win scoring; best_pick per fixture
- `football_bot/signals.py` — builds Acca-3, Acca-5, Acca-10, Mixed-15
- `football_bot/grader.py` — grades all 4 accas; auto-settles paper bets after grading
- `football_bot/paper_trading.py` — odds estimation, bet placement/settlement, P&L formatting
- `football_bot/alerts.py` — Telegram message formatters (signals, grades, performance, /paper)
- `football_bot/telegram.py` — send + async command polling (full command suite)
- `football_bot/utils.py` — shared UTC time helpers

**Workflow:** `Football Draw Bot` (console, runs `python3 football_bot/main.py`)

**Required secrets (all separate from Arb Bot):**
- `FOOTBALL_TG_TOKEN` — new bot from @BotFather
- `FOOTBALL_TG_CHAT_ID` — channel or chat ID
- `FOOTBALL_API_KEY` — free key from football-data.org

**Draw prediction model (5 factors, weighted):**
- Home team draw rate (last 20 home games) — 25%
- Away team draw rate (last 20 away games) — 25%
- Head-to-head draw rate — 20%
- Competitive balance (similar goal output) — 15%
- League draw tendency (Championship highest at 30%) — 15%

**Leagues covered (highest draw rates):**
Championship (30%), 2.Bundesliga (28%), Serie A (27%), Eredivisie (27%), Primeira Liga (27%),
Ligue 1 (26%), La Liga (26%), Bundesliga (25%), Premier League (25%), Série A Brazil (26%)

**3 accumulator types posted daily:**
- Acca-3 / Acca-5 — top draw picks scored by 5-factor model
- Mixed-15 — best outcome per match from 6 types: draw, home, away, over 1.5, over 2.5, GG/BTTS

**Goals market model (Poisson-based, added to Mixed-15):**
- Expected goals per team: blend own attack rate with opponent's defensive concession rate
- Over 1.5: P(≥2 goals) via Poisson | Over 2.5: P(≥3 goals) | GG: P(home≥1) × P(away≥1)
- Graded from match scores: over15→total≥2, over25→total≥3, gg→both>0

**Paper trading (₦1,000/acca · ₦3,000/day):**
- Odds estimated from model confidence: draw ~2.7–4.5, home ~1.6–4.0, away ~2.0–5.5
- Goals odds: over1.5 ~1.15–1.75, over2.5 ~1.55–2.45, gg ~1.50–2.25
- Bets auto-settled after grading; running P&L, ROI, best/worst day tracked in state.json
- Per-acca win counts, last-7-day P&L, all-time summary via /paper command

**Performance tracking:** per-pick %, per-acca hit rate (7d / 30d / all-time), per-league accuracy, mixed acca by outcome type (draw/home/away)

**Daily schedule (UTC):**
- 09:00 — posts all 4 accas + places paper bets (configurable via /setsignaltime)
- 17:00–23:00 — rolling result check every 30 min; auto-grade + settle paper bets

**Telegram commands:**
/signals, /paper, /performance, /history, /grade [DATE], /leagues, /status, /setsignaltime HH:MM, /pause, /resume, /help

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## BSC Whale Alert Bot

**Entry point:** `bsc_bot/main.py`
**Modules:** `bsc_bot/` package — completely separate from the other bots

- `bsc_bot/config.py` — thresholds, stablecoins, token groups, CEX wallets, CoinGecko IDs
- `bsc_bot/cex_labels.py` — 60+ CEX hot/cold wallet DB across 14 exchanges; signal classifier
- `bsc_bot/monitor.py` — BscScan polling, price fetching, 24h aggregation, alert cooldown
- `bsc_bot/bot.py` — Telegram send queue, command polling, alert formatting

**Workflow:** `BSC Whale Bot` (console, runs `python3 bsc_bot/main.py`)

**Required secrets:**
- `BSC_TG_TOKEN` — new bot from @BotFather
- `BSC_TG_CHAT_ID` — channel or chat ID
- `BSCSCAN_API_KEY` — free key from bscscan.com

**Signal logic:**
- 🟢 ACCUMULATION — CEX → Private wallet (bullish, coins leaving exchange)
- 🔴 DISTRIBUTION — Private wallet → CEX (bearish, coins entering exchange)
- 🟠 POSSIBLE SELL — CEX → CEX (OTC routing or disguised selling)
- 🐋 WHALE MOVE — Wallet → Wallet (OTC/cold storage, neutral)

**Thresholds:**
- ₿ BTC group (BTCB, WBTC, etc.): $2M minimum
- ⬡ ETH group (WETH, BETH, etc.): $500K minimum
- 🥇 Gold/Oil (PAXG, XAUT): $500K minimum
- 🟡 BNB-native (WBNB, CAKE, etc.): $50K minimum
- 🪙 All other alts: $20K minimum
- 💵 Stablecoins: skipped entirely (no alerts)
- Hard dust filter: $100 minimum regardless of token

**Key features:**
- Scans ALL BEP-20 tokens by monitoring 60+ CEX hot wallets — no predefined token list needed
- Stablecoin filter: USDT, USDC, BUSD, DAI, and 40+ pegs fully suppressed
- 24h rolling aggregation per wallet+token pair — fires updated alert on each new tranche
- 5-minute alert cooldown per wallet+token — prevents spam on rapid buys
- Unknown token price lookup via CoinGecko search before discarding
- Whale score: 🦈/🦈🦈/🦈🦈🦈 multiplier badge on oversized moves
- Block time → age indicator on each alert (e.g. "42s ago")

**Telegram commands:**
/start, /help, /status, /summary, /top, /config, /pause, /resume

## Base Chain Whale Alert Bot

**Entry point:** `base_main.py`
**Modules:** `base_bot/` package — completely separate from other bots

- `base_bot/config.py` — RPC endpoints, thresholds, stablecoins, Base token addresses
- `base_bot/cex_labels.py` — 35+ CEX/DEX/Bridge address DB; classify() signal router
- `base_bot/monitor.py` — eth_getLogs Transfer scanner, rotation tracker, cluster detector
- `base_bot/bot.py` — Telegram queue, command polling, alert formatters

**Workflow:** `Base Whale Bot` (console, runs `python3 base_main.py`)

**Required secrets:**
- `BASE_TG_TOKEN` — new bot from @BotFather
- `BASE_TG_CHAT_ID` — channel or chat ID

**Signal types:**
- 🟢 ACCUMULATION — CEX → Private wallet (bullish)
- 🔴 DISTRIBUTION — Private wallet → CEX (bearish)
- 🟠 POSSIBLE SELL — CEX → CEX
- 🐋 WHALE MOVE — Wallet → Wallet
- 🌉🟢 BRIDGE INFLOW — capital arriving on Base (institutional buy signal)
- 🌉🔴 BRIDGE OUTFLOW — capital leaving Base
- 🚨 CONCENTRATION — 3+ unique wallets, same token, same direction, 60 min
- 🔄 SMART MONEY ROTATION — BRETT/TOSHI top holder rotated into new token (2–5× signal)

Note: DEX signals (Aerodrome, Uniswap V3) are intentionally suppressed — DEX swap events are noise.

**Thresholds:** same as BSC bot (BTC $2M, ETH $500K, AERO $50K, alts $20K, stables suppressed)

**Base-specific features:**
- Monitors Aerodrome Finance (Sugar + Slipstream) and Uniswap V3 large swaps
- Tracks Base Bridge (L2StandardBridge) flows for institutional on/off-ramping
- BRETT/TOSHI smart money rotation: 4-hour tracking window, $10K minimum
- 7 free public Base RPC endpoints — no API key required

**Telegram commands:**
/status, /top, /rotation, /config, /pause, /resume, /help

**Railway zip:** `base-whale-bot.zip`

## User Preferences

- **BSC bot zip**: After every change to any `bsc_bot/` file or `bsc_main.py`, always rebuild `bsc-whale-bot.zip` (sync updated files into `/tmp/bsc-whale-bot/bsc_bot/`, rebuild zip, copy to workspace root) and present it for download.
- **Base bot zip**: After every change to any `base_bot/` file or `base_main.py`, always rebuild `base-whale-bot.zip` (sync updated files into `/tmp/base-whale-bot/base_bot/`, rebuild zip, copy to workspace root) and present it for download.
