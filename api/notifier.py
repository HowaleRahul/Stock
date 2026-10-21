import os
import logging
import requests
from dotenv import load_dotenv
from typing import Optional, Dict, Any

load_dotenv()

logger = logging.getLogger("trading.notifier")

import html
import concurrent.futures

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="notifier")

class Notifier:
    """
    Sends trade alerts to external channels (Telegram, WhatsApp, etc.).
    Fails gracefully if credentials are not configured.
    """
    
    def __init__(self):
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.is_telegram_enabled = bool(self.telegram_token and self.telegram_chat_id)
        
        if not self.is_telegram_enabled:
            logger.info("Telegram notifications disabled (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env).")

    def _send_telegram(self, message: str) -> bool:
        if not self.is_telegram_enabled:
            return False
            
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            return True
        except Exception as e:
            # Mask sensitive bot token in logs
            safe_err = str(e)
            if self.telegram_token:
                safe_err = safe_err.replace(self.telegram_token, "***")
            logger.error(f"Failed to send Telegram alert: {safe_err}")
            return False

    def _dispatch_async(self, message: str) -> None:
        """Dispatch notification in background thread to avoid blocking trading execution."""
        if not self.is_telegram_enabled:
            return
        try:
            _executor.submit(self._send_telegram, message)
        except Exception as e:
            logger.warning(f"Could not dispatch telegram notification: {e}")

    def send_entry_alert(self, trade: Dict[str, Any], is_live: bool = False):
        """Send an alert when a new trade is opened."""
        env_str = "🔴 LIVE" if is_live else "📄 PAPER"
        asset_type = "OPTIONS" if trade.get("is_options") else "EQUITY"
        ticker = html.escape(str(trade.get('ticker', 'UNKNOWN')))
        direction = html.escape(str(trade.get('direction', '')))
        opt_type = html.escape(str(trade.get('opt_type', '')))
        
        msg = f"<b>{env_str} TRADE OPENED ({asset_type})</b>\n\n"
        msg += f"<b>Ticker:</b> {ticker}\n"
        msg += f"<b>Direction:</b> {direction} / {opt_type}\n"
        msg += f"<b>Quantity:</b> {trade.get('quantity', 0)} units\n"
        msg += f"<b>Invested:</b> ₹{trade.get('invested', 0):,.2f}\n\n"
        
        msg += f"<b>Entry:</b> ₹{trade.get('entry_price', 0):,.2f}\n"
        msg += f"<b>Target:</b> ₹{trade.get('tp', 0):,.2f}\n"
        msg += f"<b>Stop:</b> ₹{trade.get('sl', 0):,.2f}\n"
        
        if "risk_reward" in trade and trade.get("risk_reward") is not None:
            msg += f"<b>R:R:</b> {float(trade.get('risk_reward', 0)):.2f}:1\n"
            
        if "probability" in trade and trade.get("probability") is not None:
            msg += f"<b>AI Conf:</b> {float(trade.get('probability', 0))*100:.1f}%\n"
            
        self._dispatch_async(msg)

    def send_exit_alert(self, trade: Dict[str, Any], is_live: bool = False):
        """Send an alert when a trade is closed."""
        env_str = "🔴 LIVE" if is_live else "📄 PAPER"
        ticker = html.escape(str(trade.get('ticker', 'UNKNOWN')))
        reason = html.escape(str(trade.get('status', 'UNKNOWN')))
        
        pnl_pct = (trade.get("pnl_pct") or 0.0) * 100
        cash_pnl = trade.get("cash_pnl") or 0.0
        
        icon = "🟩" if pnl_pct > 0 else "🟥"
        
        msg = f"<b>{env_str} TRADE CLOSED</b> {icon}\n\n"
        msg += f"<b>Ticker:</b> {ticker}\n"
        msg += f"<b>Reason:</b> {reason}\n"
        msg += f"<b>Exit Price:</b> ₹{trade.get('exit_price', 0):,.2f}\n\n"
        
        msg += f"<b>Net P&L:</b> {pnl_pct:+.2f}%\n"
        msg += f"<b>Cash P&L:</b> ₹{cash_pnl:+,.2f}\n"
        
        self._dispatch_async(msg)
        
    def send_system_alert(self, message: str, level: str = "INFO"):
        """Send generic system alerts (e.g. drift detected, killswitch)."""
        icons = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "CRITICAL": "🚨"
        }
        icon = icons.get(level.upper(), "ℹ️")
        safe_message = html.escape(str(message))
        
        msg = f"{icon} <b>SYSTEM ALERT</b> {icon}\n\n{safe_message}"
        self._dispatch_async(msg)

# Global singleton instance
notifier = Notifier()
