import asyncio
import datetime
import email.utils
import ipaddress
import logging
import socket
import urllib.parse
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
import httpx
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

try:
    import defusedxml.ElementTree as defused_ET
except ImportError:
    defused_ET = None

logger = logging.getLogger("trading.data.news_fetcher")

def _is_safe_redirect(target_url: str) -> bool:
    """Validate redirect destination against SSRF: only HTTPS and public IP addresses allowed."""
    try:
        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme != "https":
            return False
        # Block non-standard ports to prevent internal port scanning
        if parsed.port and parsed.port != 443:
            return False
        host = parsed.hostname
        if not host:
            return False
        # Direct IP check
        try:
            ip = ipaddress.ip_address(host)
            if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        except ValueError:
            # Resolve hostname and verify resolved IPs
            addr_info = socket.getaddrinfo(host, 443)
            for item in addr_info:
                ip_str = item[4][0]
                ip = ipaddress.ip_address(ip_str)
                if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped:
                    ip = ip.ipv4_mapped
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    return False
        return True
    except Exception as e:
        logger.warning(f"SSRF safety check failed for {target_url}: {e}")
        return False


def _safe_parse_xml(xml_text: str) -> ET.Element:
    """Parse XML with defusedxml (if available) or strict entity/DTD protection."""
    if len(xml_text) > 5_000_000:
        raise ValueError("XML payload exceeds maximum allowable size (5MB).")

    if defused_ET is not None:
        return defused_ET.fromstring(xml_text)
    
    # Defense against XML entity expansion (billion laughs, quadratic blowup, XXE)
    upper = xml_text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("Rejected suspicious XML payload containing DOCTYPE or ENTITY declaration.")
    return ET.fromstring(xml_text)

# Initialize and tune VADER for financial and options market context
_SIA = SentimentIntensityAnalyzer()
_SIA.lexicon.update({
    "crash": -3.5,
    "tank": -3.0,
    "plunge": -3.0,
    "drops": -2.0,
    "drop": -2.0,
    "fall": -2.0,
    "losses": -2.0,
    "sell-off": -2.5,
    "selloff": -2.5,
    "tumble": -2.5,
    "slump": -2.5,
    "decline": -1.8,
    "deficit": -1.8,
    "surge": 2.5,
    "rally": 2.5,
    "jump": 2.0,
    "gain": 2.0,
    "gains": 2.0,
    "soar": 2.8,
    "bullish": 2.5,
    "bearish": -2.5,
    "breakout": 2.2,
    "highs": 2.0,
})


class NewsFetcher:
    """
    Asynchronous aggregator for Indian market news headlines and sentiment.
    Combines direct Indian financial market RSS feeds (Google News IN / Moneycontrol)
    with Yahoo Finance fallback and financial VADER sentiment scoring.
    """

    @staticmethod
    def calculate_sentiment(text: str) -> Dict[str, Any]:
        """Calculates financial sentiment score and classification label."""
        if not text:
            return {"compound": 0.0, "label": "NEUTRAL", "pos": 0.0, "neg": 0.0}
        scores = _SIA.polarity_scores(text)
        compound = float(scores.get("compound", 0.0))
        if compound >= 0.15:
            label = "BULLISH"
        elif compound <= -0.15:
            label = "BEARISH"
        else:
            label = "NEUTRAL"
        return {
            "compound": round(compound, 3),
            "label": label,
            "pos": round(scores.get("pos", 0.0), 3),
            "neg": round(scores.get("neg", 0.0), 3),
        }

    @classmethod
    def _fetch_indian_rss_news_sync(cls, ticker: str, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Fetches live Indian financial news headlines from the public Google News India RSS feed.
        Zero authentication required, highly reliable, and covers all NSE/BSE indices.
        """
        if not ticker or not isinstance(ticker, str):
            return []
        clean = ticker.upper().strip().replace("\x00", "")[:64]
        if clean in ("NIFTY", "^NSEI", "NIFTY50", "NIFTY 50"):
            query = "NIFTY 50 Indian stock market"
        elif clean in ("BANKNIFTY", "^NSEBANK", "BANK NIFTY"):
            query = "BANK NIFTY Indian banking stocks"
        elif clean in ("SENSEX", "^BSESN", "BSE"):
            query = "BSE SENSEX Indian stock market"
        elif clean in ("FINNIFTY",):
            query = "NIFTY financial services stocks"
        elif clean in ("MIDCPNIFTY",):
            query = "NIFTY midcap stocks market"
        else:
            query = f"{clean} share price India stock market"

        encoded_query = urllib.parse.quote_plus(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        headlines = []

        try:
            current_url = rss_url
            resp = None
            with httpx.Client(timeout=8.0, follow_redirects=False) as client:
                # Follow redirects with SSRF validation up to 3 hops
                for _ in range(4):
                    resp = client.get(current_url)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location")
                        if not loc:
                            break
                        next_url = urllib.parse.urljoin(current_url, loc)
                        if not _is_safe_redirect(next_url):
                            logger.warning(f"Blocked unsafe SSRF redirect to: {next_url}")
                            return []
                        current_url = next_url
                    else:
                        break

                if resp is None or resp.status_code != 200:
                    logger.warning(f"Indian RSS news returned status {resp.status_code if resp else 'None'}")
                    return []

                root = _safe_parse_xml(resp.text)
                items = root.findall(".//item")[:limit]

                for item in items:
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    pub_elem = item.find("pubDate")
                    source_elem = item.find("source")

                    if title_elem is None or not title_elem.text:
                        continue

                    title = title_elem.text.strip()
                    url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    source = source_elem.text.strip() if source_elem is not None and source_elem.text else "Financial Press"

                    pub_time = datetime.datetime.now(datetime.timezone.utc)
                    if pub_elem is not None and pub_elem.text:
                        try:
                            parsed_dt = email.utils.parsedate_to_datetime(pub_elem.text)
                            if parsed_dt.tzinfo is None:
                                pub_time = parsed_dt.replace(tzinfo=datetime.timezone.utc)
                            else:
                                pub_time = parsed_dt.astimezone(datetime.timezone.utc)
                        except Exception:
                            pass

                    sent = cls.calculate_sentiment(title)

                    headlines.append({
                        "time": pub_time,
                        "url": str(url)[:1020],
                        "title": str(title)[:510],
                        "source": str(source)[:120],
                        "summary": None,
                        "sentiment_score": sent["compound"],
                        "sentiment_label": sent["label"],
                    })

            logger.info(f"Retrieved {len(headlines)} Indian market RSS headlines for {ticker}.")
        except Exception as e:
            logger.warning(f"Error fetching Indian RSS news for {ticker}: {e}")

        return headlines

    @classmethod
    def _fetch_news_sync(cls, ticker: str) -> List[Dict[str, Any]]:
        """
        Unified sync news fetcher:
        1. Tries Indian RSS feed first for index underlyings or when yfinance is empty.
        2. Queries yfinance news as complementary source.
        """
        clean = ticker.upper().strip()
        is_index = clean in ("NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "^NSEI", "^NSEBANK", "^BSESN")

        if is_index:
            rss_headlines = cls._fetch_indian_rss_news_sync(clean)
            if rss_headlines:
                return rss_headlines

        # Try yfinance for individual tickers
        headlines = []
        try:
            yt = yf.Ticker(ticker)
            raw_news = yt.news or []
            for item in raw_news:
                if not isinstance(item, dict):
                    continue

                content = item.get("content", item)
                if not isinstance(content, dict):
                    continue

                title = content.get("title") or item.get("title", "")
                if not title:
                    continue

                summary = content.get("summary") or item.get("summary", "")

                # Extract URL (supports string or dict for clickThroughUrl / canonicalUrl)
                url = None
                if "canonicalUrl" in content and isinstance(content["canonicalUrl"], dict):
                    url = content["canonicalUrl"].get("url")
                elif "clickThroughUrl" in content and isinstance(content["clickThroughUrl"], dict):
                    url = content["clickThroughUrl"].get("url")

                if not url:
                    url = content.get("clickThroughUrl") or content.get("url") or item.get("link") or item.get("url")

                if not url or not isinstance(url, str):
                    continue

                # Parse publication time (ISO string or unix timestamp)
                pub_time = None
                if "pubDate" in content and content["pubDate"]:
                    try:
                        pub_time = datetime.datetime.fromisoformat(str(content["pubDate"]).replace("Z", "+00:00"))
                    except Exception:
                        pass

                if not pub_time:
                    ts = content.get("providerPublishTime") or item.get("providerPublishTime")
                    if ts and isinstance(ts, (int, float)):
                        try:
                            pub_time = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                        except Exception:
                            pass

                if not pub_time:
                    pub_time = datetime.datetime.now(datetime.timezone.utc)
                elif pub_time.tzinfo is None:
                    pub_time = pub_time.replace(tzinfo=datetime.timezone.utc)

                # Extract publisher
                source = "Financial Press"
                if "provider" in content and isinstance(content["provider"], dict):
                    source = content["provider"].get("displayName", source)
                elif item.get("publisher"):
                    source = item.get("publisher")

                sent = cls.calculate_sentiment(title)
                headlines.append({
                    "time": pub_time,
                    "url": str(url)[:1020],
                    "title": str(title)[:510],
                    "source": str(source)[:120],
                    "summary": (str(summary)[:2000] if summary else None),
                    "sentiment_score": sent["compound"],
                    "sentiment_label": sent["label"],
                })
        except Exception as e:
            logger.debug(f"yfinance news failed for {ticker}: {e}")

        # If yfinance returned empty, fallback to Indian RSS feed
        if not headlines:
            headlines = cls._fetch_indian_rss_news_sync(clean)

        return headlines

    @classmethod
    async def fetch_ticker_news(cls, ticker: str) -> List[Dict[str, Any]]:
        """Asynchronously fetches and standardizes news headlines for a ticker."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(cls._fetch_news_sync, ticker), timeout=25.0)
        except asyncio.TimeoutError:
            logger.error(f"News request timed out while fetching headlines for {ticker}.")
            return []

    @classmethod
    async def get_sentiment_summary(cls, ticker: str) -> Dict[str, Any]:
        """Returns aggregated news sentiment metrics for a ticker."""
        headlines = await cls.fetch_ticker_news(ticker)
        if not headlines:
            return {
                "ticker": ticker,
                "total_headlines": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "overall_sentiment": "NEUTRAL",
                "mean_score": 0.0,
                "headlines": []
            }

        bullish = sum(1 for h in headlines if h.get("sentiment_label") == "BULLISH")
        bearish = sum(1 for h in headlines if h.get("sentiment_label") == "BEARISH")
        neutral = sum(1 for h in headlines if h.get("sentiment_label") == "NEUTRAL")
        scores = [float(h.get("sentiment_score", 0.0)) for h in headlines]
        mean_score = sum(scores) / len(scores) if scores else 0.0

        if mean_score >= 0.15:
            overall = "BULLISH"
        elif mean_score <= -0.15:
            overall = "BEARISH"
        else:
            overall = "NEUTRAL"

        return {
            "ticker": ticker,
            "total_headlines": len(headlines),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "overall_sentiment": overall,
            "mean_score": round(mean_score, 3),
            "headlines": headlines[:15]
        }
