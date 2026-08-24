"""
Main scan loop — async, concurrent fetching across all tokens.
Known pools are persisted in state so restarts don't re-spam new-pool alerts.
"""
import asyncio
import html as _html
from collections import defaultdict

from bot.config import CHAIN_EMOJIS
from bot.fetcher import fetch_all_pools
from bot.analyzer import find_intra_gap, detect_new_pools
from bot.alerts import build_intra_alert, build_new_pool_alert
from bot.utils import fmt_usd, now_ts
from bot.executor import simulate
from bot.live_executor import (live_execute, jupiter_roundtrip_scan, jupiter_direct_execute,
                               jupiter_preflight_quick, TOKEN_MINTS)
import bot.pnl as pnl
import bot.state as state
import bot.telegram as tg


async def run_scan():
    if state.is_paused():
        print(f"[{now_ts()}] ⏸  Paused — skipping scan")
        return

    scan_num = state.inc_scan()
    wl       = state.watchlist()
    by_chain = defaultdict(int)
    for v in wl.values():
        by_chain[v["chain"]] += 1

    print(f"\n[{now_ts()}] Scan #{scan_num} — SOL:{by_chain['sol']}")

    all_pools   = await fetch_all_pools(wl)
    known_pools = state.get_known_pools()   # persistent across restarts
    best_gap    = None
    is_first    = (scan_num == 1)

    for key, token in wl.items():
        chain  = token["chain"]
        symbol = token["symbol"]
        pools  = all_pools.get(key, [])
        ce     = CHAIN_EMOJIS.get(chain, "")

        if not pools:
            print(f"  {ce}[{symbol}] No pools found")
            continue

        prices = [round(p["price_usd"], 8) for p in pools[:4]]
        print(f"  {ce}[{symbol}] {len(pools)} pools | {prices}")

        # ── New pool detection ─────────────────────────────────────
        # known_pools is persistent — so only truly brand-new pools alert.
        # is_first guard handles the very first run when state.json is empty.
        already_had_pools = bool(known_pools.get(key))
        new_pools = detect_new_pools(key, pools, known_pools)
        state.update_known_pools(key, known_pools[key])

        if already_had_pools and new_pools:
            for p in new_pools:
                await tg.send(build_new_pool_alert(chain, symbol, p))
                print(f"  {ce}[{symbol}] 🆕 New pool: {p['dex_name']}")
        elif new_pools:
            print(f"  {ce}[{symbol}] Seeded {len(new_pools)} pool(s) (first time seeing token)")

        # ── Intra-chain arb ───────────────────────────────────────
        gap = find_intra_gap(chain, symbol, token["address"], pools)
        if gap:
            spread  = gap["spread_pct"]
            conf    = gap["confidence"]
            min_conf = state.cfg_confidence()
            print(f"  {ce}[{symbol}] ⚡ INTRA GAP: {spread:.2f}%  "
                  f"slip={gap['slip_buy_pct']:.3f}%/{gap['slip_sell_pct']:.3f}%  "
                  f"net={fmt_usd(gap['net_profit'])}  conf={conf}/{min_conf}")

            # Always log the opportunity; only alert if confidence passes threshold
            state.log_opportunity(gap)

            if conf < min_conf:
                print(f"  {ce}[{symbol}] 🔇 Suppressed (conf {conf} < {min_conf}) — logged only")
            elif state.already_alerted_today(key) and state.get("automode") != "live":
                # In LIVE mode we skip the "once-per-day" gate — the cooldown timer
                # already throttles re-trades.  The daily cap kills repeat profitable
                # opportunities (e.g. PENGU fired 69 times today, any could be real).
                print(f"  {ce}[{symbol}] 🚫 Already alerted today — skipping")
            elif state.cooldown_ok(key, state.cfg_cooldown()):
                automode = state.get("automode")

                # ── Live SOL: Jupiter pre-flight BEFORE alerting ────────
                # Prevents spamming Telegram with "EXECUTING…" + "FAILED"
                # pairs when DexScreener shows a stale/phantom gap that
                # Jupiter's own routing has already closed.
                if automode == "live" and chain == "sol" and state.get("live_confirmed"):
                    live_size = state.cfg_live_trade_size()
                    pf_ok, pf_net, pf_msg = await jupiter_preflight_quick(symbol, live_size)
                    if not pf_ok:
                        print(f"  {ce}[{symbol}] ⛔ Pre-flight failed — {pf_msg}")
                        print(f"  {ce}[{symbol}]    Gap dead or DexScreener stale. No alert sent.")
                        # Do NOT update cooldown/alerted — this gap was never real.
                        # It will be re-checked next scan cycle.
                    else:
                        # Pre-flight confirmed profitable → alert then execute
                        state.set_alerted(key)
                        state.mark_alerted_today(key)
                        await tg.send(build_intra_alert(gap))
                        print(f"  {ce}[{symbol}] ✅ Alert sent (Jupiter pre-flight: {pf_msg})")
                        if best_gap is None or spread > best_gap["spread_pct"]:
                            best_gap = gap
                        print(f"  {ce}[{symbol}] 💸 LIVE TRADE executing (size=${live_size:.2f})...")
                        gas_cost = 0.025 * 2  # $0.025/leg × 2
                        expected_out = live_size + pf_net + gas_cost
                        pf_pct = (pf_net / live_size) * 100
                        await tg.send(
                            f"💸 <b>LIVE TRADE EXECUTING</b>  [{symbol} / SOL]\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"USDC in:       <b>${live_size:.2f}</b>\n"
                            f"Expected out:  <b>${expected_out:.4f}</b>\n"
                            f"Gas (2 txns):  <b>-${gas_cost:.3f}</b>\n"
                            f"<b>Projected net: +${pf_net:.4f} ({pf_pct:+.2f}%)</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"Spread: {spread:.2f}%  |  Conf: {conf}/100\n"
                            f"Route: {gap['buy_pool'].get('dex_name','?')} → "
                            f"{gap['sell_pool'].get('dex_name','?')}\n"
                            f"<i>P&amp;L verified by Jupiter — submitting now...</i>"
                        )
                        try:
                            trade = await live_execute(gap)
                            pnl.record_trade(trade)
                            result_icon = "✅" if trade["win"] else "❌"
                            explorer1 = f"https://solscan.io/tx/{trade['tx_leg1']}"
                            explorer2 = f"https://solscan.io/tx/{trade['tx_leg2']}"
                            print(f"  {ce}[{symbol}] 💸 LIVE {result_icon} "
                                  f"Net {fmt_usd(trade['net_profit'])} | "
                                  f"In: ${trade['usdc_in']:.2f} Out: ${trade['usdc_out']:.4f}")
                            await tg.send(
                                f"{'✅' if trade['win'] else '❌'} <b>LIVE TRADE COMPLETE</b>  "
                                f"[{symbol} / SOL]\n"
                                f"USDC in:  <b>${trade['usdc_in']:.2f}</b>\n"
                                f"USDC out: <b>${trade['usdc_out']:.4f}</b>\n"
                                f"Net P&amp;L: <b>{fmt_usd(trade['net_profit'])}</b>\n"
                                f"Spread: {spread:.2f}%  |  Conf: {conf}/100\n"
                                f"Route: {trade['route']}\n"
                                f"<a href='{explorer1}'>Leg 1 on Solscan</a>  ·  "
                                f"<a href='{explorer2}'>Leg 2 on Solscan</a>"
                            )
                        except Exception as exc:
                            print(f"  {ce}[{symbol}] 💸 LIVE TRADE FAILED: {exc}")
                            await tg.send(
                                f"⚠️ <b>LIVE TRADE FAILED</b>  [{symbol} / SOL]\n"
                                f"<code>{_html.escape(str(exc)[:300])}</code>\n"
                                f"<i>No funds lost — transaction rejected before submission.</i>"
                            )

                else:
                    # ── Dry-run / monitor: alert immediately (no money at risk) ──
                    state.set_alerted(key)
                    state.mark_alerted_today(key)
                    await tg.send(build_intra_alert(gap))
                    print(f"  {ce}[{symbol}] ✅ Alert sent")
                    if best_gap is None or spread > best_gap["spread_pct"]:
                        best_gap = gap
                    if automode == "dry":
                        trade = simulate(gap, max_trade_usd=state.cfg_max_sim_size())
                        pnl.record_trade(trade)
                        result_icon = "✅" if trade["win"] else "❌"
                        print(f"  {ce}[{symbol}] 🧪 DRY-RUN: {result_icon} "
                              f"Net {fmt_usd(trade['net_profit'])} on ${trade['sim_size']:.0f} sim")
                        await tg.send(
                            f"🧪 <b>DRY-RUN EXECUTED</b>  [{symbol} / {chain.upper()}]\n"
                            f"{result_icon} Net: <b>{fmt_usd(trade['net_profit'])}</b>  "
                            f"on ${trade['sim_size']:.0f} sim\n"
                            f"Spread: {spread:.2f}%  |  Conf: {conf}/100\n"
                            f"Route: {trade['route']}\n"
                            f"<i>No real money moved — simulation only</i>"
                        )
            else:
                rem = state.cooldown_remaining(key, state.cfg_cooldown())
                print(f"  {ce}[{symbol}] 🕐 Cooldown {rem}s remaining")
        else:
            print(f"  {ce}[{symbol}] No gap >{state.cfg_spread()}%")

    # ── Persist known pools once per scan ─────────────────────────
    state.save_known_pools()
    cross_gaps = []  # BSC removed — no cross-chain

    # ── Jupiter Direct Round-Trip Scan ────────────────────────────
    # Ask Jupiter itself whether any token round-trip is profitable
    # right now.  Runs every scan, independent of DexScreener gaps.
    # Only active when automode is dry or live — not in monitor mode.
    #
    # To stay within Jupiter's free-tier rate limit, we check only a
    # rotating batch of 6 tokens per scan (full rotation every 4 scans
    # ≈ 4 minutes).  Each batch = 12 Jupiter calls with 0.4 s gaps ≈ 10s.
    JDIRECT_BATCH = 6
    automode = state.get("automode")
    if automode in ("dry", "live"):
        all_mints   = list(TOKEN_MINTS.items())   # [(symbol, mint), ...]
        batch_start = (scan_num % max(1, len(all_mints) // JDIRECT_BATCH)) * JDIRECT_BATCH
        token_items = all_mints[batch_start : batch_start + JDIRECT_BATCH]
        jdirect_size = state.cfg_live_trade_size()
        try:
            jdirect_opps = await jupiter_roundtrip_scan(token_items, trade_size=jdirect_size)
        except Exception as je:
            print(f"[JupDirect] Scan error: {je}")
            jdirect_opps = []

        if jdirect_opps:
            for opp in jdirect_opps:
                sym     = opp["symbol"]
                net_pct = opp["net_pct"]
                net_usd = opp["net_usd"]
                print(f"  🟢[{sym}] JUPITER DIRECT: round-trip net "
                      f"{net_pct:.3f}% / {fmt_usd(net_usd)}")
                await tg.send(
                    f"🟢 <b>JUPITER DIRECT ARB — {sym}/SOL</b>\n"
                    f"Net: <b>{fmt_usd(net_usd)}</b>  ({net_pct:.3f}%)\n"
                    f"USDC in: ${opp['usdc_in']:.2f} → out: ${opp['usdc_out']:.4f}\n"
                    f"Route: Jupiter smart routing (USDC→{sym}→USDC)\n"
                    f"<i>Quote confirmed profitable — executing now...</i>"
                )
                if automode == "dry":
                    print(f"  🧪[{sym}] DRY-RUN: would net {fmt_usd(net_usd)}")
                    await tg.send(
                        f"🧪 <b>DRY-RUN</b>  [{sym} Jupiter Direct]\n"
                        f"Would net <b>{fmt_usd(net_usd)}</b> ({net_pct:.3f}%)\n"
                        f"<i>No real money moved — automode is dry</i>"
                    )
                elif automode == "live" and state.get("live_confirmed"):
                    print(f"  💸[{sym}] JUPITER DIRECT LIVE — executing...")
                    try:
                        trade = await jupiter_direct_execute(opp)
                        pnl.record_trade(trade)
                        icon = "✅" if trade["win"] else "❌"
                        e1   = f"https://solscan.io/tx/{trade['tx_leg1']}"
                        e2   = f"https://solscan.io/tx/{trade['tx_leg2']}"
                        print(f"  💸[{sym}] {icon} Net {fmt_usd(trade['net_profit'])} "
                              f"| in=${trade['usdc_in']:.2f} out=${trade['usdc_out']:.4f}")
                        await tg.send(
                            f"{icon} <b>JUPITER DIRECT COMPLETE — {sym}</b>\n"
                            f"USDC in:  <b>${trade['usdc_in']:.2f}</b>\n"
                            f"USDC out: <b>${trade['usdc_out']:.4f}</b>\n"
                            f"Net P&amp;L: <b>{fmt_usd(trade['net_profit'])}</b>\n"
                            f"<a href='{e1}'>Leg 1 on Solscan</a>  ·  "
                            f"<a href='{e2}'>Leg 2 on Solscan</a>"
                        )
                    except Exception as exc:
                        err_str = str(exc)
                        # Only warn about Leg 1 executing if the error mentions Leg 2
                        # or confirmation — meaning Leg 1 already went through.
                        leg1_went_through = any(x in err_str for x in ("Leg 2", "confirmed", "not confirmed"))
                        footer = (
                            "<i>⚠️ Leg 1 may have executed — check your wallet on Solscan.</i>"
                            if leg1_went_through else
                            "<i>No funds moved — error occurred before any transaction was submitted.</i>"
                        )
                        print(f"  💸[{sym}] JUPITER DIRECT FAILED: {exc}")
                        await tg.send(
                            f"⚠️ <b>JUPITER DIRECT FAILED — {sym}</b>\n"
                            f"<code>{_html.escape(err_str[:300])}</code>\n"
                            f"{footer}"
                        )
        else:
            print(f"[JupDirect] No profitable round-trips found this scan")

    if best_gap:
        ce = CHAIN_EMOJIS.get(best_gap["chain"], "")
        print(f"\n[Best] {ce}${best_gap['symbol']} "
              f"{best_gap['spread_pct']:.2f}% | Net: {fmt_usd(best_gap['net_profit'])}")
    else:
        print(f"[Scan #{scan_num}] No gaps above {state.cfg_spread()}%")
