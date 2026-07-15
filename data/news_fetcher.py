import asyncio
import datetime
import logging
from typing import List, Dict, Any
import yfinance as yf

logger = logging.getLogger("trading.data.news_fetcher")

class NewsFetcher:
    """
    Async wrapper for pulling financial news headlines linked to specific tickers.
    Currently leverages yfinance ticker news feeds without requiring external API keys.
    """

    @staticmethod
    def _fetch_news_sync(ticker: str) -> List[Dict[str, Any]]:
        logger.info(f"Downloading news headlines for {ticker}...")
        yt = yf.Ticker(ticker)
        try:
            raw_news = yt.news or []
        except Exception as e:
            logger.warning(f"Error fetching news for {ticker}: {e}")
            return []

        headlines = []
        for item in raw_news:
            try:
                # Handle both dict formats depending on yfinance version
                content = item.get("content", item)
                title = content.get("title") or item.get("title", "")
                summary = content.get("summary") or item.get("summary", "")
                
                # Extract URL
                url = ""
                if "canonicalUrl" in content and isinstance(content["canonicalUrl"], dict):
                    url = content["canonicalUrl"].get("url", "")
                if not url:
                    url = content.get("clickThroughUrl") or content.get("url") or item.get("link") or item.get("url", "")

                # Extract publish time
                pub_time = None
                if "pubDate" in content and content["pubDate"]:
                    # ISO string or timestamp
                    try:
                        pub_time = datetime.datetime.fromisoformat(content["pubDate"].replace("Z", "+00:00"))
                    except Exception:
                        pass
                if not pub_time:
                    ts = content.get("providerPublishTime") or item.get("providerPublishTime")
                    if ts and isinstance(ts, (int, float)):
                        pub_time = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)

                if not pub_time:
                    pub_time = datetime.datetime.now(datetime.timezone.utc)
                elif pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=datetime.timezone.utc)

                # Extract source publisher
                source = "Yahoo Finance"
                if "provider" in content and isinstance(content["provider"], dict):
                    source = content["provider"].get("displayName", source)
                elif item.get("publisher"):
                    source = item.get("publisher")

                if title and url:
                    headlines.append({
                        "time": pub_time,
                        "url": str(url)[:1020],
                        "title": str(title)[:510],
                        "source": str(source)[:120],
                        "summary": (str(summary)[:2000] if summary else None)
                    })
            except Exception as e:
                logger.debug(f"Skipping malformed news item for {ticker}: {e}")
                continue

        logger.info(f"Retrieved {len(headlines)} news headlines for {ticker}.")
        return headlines

    @classmethod
    async def fetch_ticker_news(cls, ticker: str) -> List[Dict[str, Any]]:
        """
        Asynchronously fetches and standardizes news headlines for a ticker.
        """
        try:
            return await asyncio.wait_for(asyncio.to_thread(cls._fetch_news_sync, ticker), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error(f"News request timed out (30s) while fetching headlines for {ticker}.")
            return []
