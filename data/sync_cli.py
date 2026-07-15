import argparse
import asyncio
import logging
import sys
from data.service import DataIngestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("trading.data.sync_cli")

async def run_sync(args):
    """Executes the data synchronization task based on CLI arguments."""
    logger.info("=" * 60)
    logger.info("🚀 Starting Automated Data Pipeline Synchronization CLI")
    logger.info("=" * 60)

    results = []
    if args.watchlist:
        logger.info(f"Syncing entire active watchlist (period={args.period}, interval={args.interval}, news={args.news})...")
        res = await DataIngestionService.sync_watchlist(
            period=args.period,
            interval=args.interval,
            sync_news=args.news
        )
        results.extend(res)
    elif args.ticker:
        logger.info(f"Syncing single ticker: {args.ticker} (period={args.period}, interval={args.interval})...")
        res = await DataIngestionService.sync_symbol_ohlcv(
            ticker=args.ticker,
            period=args.period,
            interval=args.interval
        )
        results.append(res)
        if args.news:
            logger.info(f"Syncing news headlines for {args.ticker}...")
            news_res = await DataIngestionService.sync_symbol_news(args.ticker)
            results.append(news_res)
    else:
        logger.error("Must specify either --ticker <SYMBOL> or --watchlist")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("✅ Synchronization Results Summary:")
    for r in results:
        logger.info(f" -> {r}")
    logger.info("=" * 60)
    return results

async def run_daemon(args):
    """Runs data synchronization continuously on a scheduled interval loop."""
    logger.info(f"🔄 Starting daemon loop every {args.loop_minutes} minutes.")
    while True:
        try:
            await run_sync(args)
        except Exception as e:
            logger.error(f"Error during scheduled sync run: {e}")
        logger.info(f"Sleeping for {args.loop_minutes} minutes until next scheduled sync...")
        await asyncio.sleep(args.loop_minutes * 60)

def main():
    parser = argparse.ArgumentParser(description="Trading System Phase 1 Data Ingestion CLI")
    parser.add_argument("--ticker", "-t", type=str, help="Specific symbol ticker to sync (e.g. RELIANCE.NS, AAPL)")
    parser.add_argument("--watchlist", "-w", action="store_true", help="Sync all active symbols in the watchlist")
    parser.add_argument("--period", "-p", type=str, default="1mo", help="Historical period (e.g. 1mo, 1y, 5y)")
    parser.add_argument("--interval", "-i", type=str, default="1d", help="Candle timeframe (e.g. 1d, 1h, 15m)")
    parser.add_argument("--news", "-n", action="store_true", help="Also sync financial news headlines")
    parser.add_argument("--loop-minutes", "-l", type=int, default=0, help="If > 0, runs continuously on this interval in minutes")

    args = parser.parse_args()
    if not args.ticker and not args.watchlist:
        parser.print_help()
        sys.exit(1)

    if args.loop_minutes > 0:
        asyncio.run(run_daemon(args))
    else:
        asyncio.run(run_sync(args))

if __name__ == "__main__":
    main()
