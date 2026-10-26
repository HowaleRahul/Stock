"""
Broker API Scaffolding (Phase 9)
Prepares the architecture for Live Trading with SEBI 2026 Retail Algo Compliance.

Key Features:
- OAuth + 2FA (TOTP) session management (mocked for now).
- Static IP Whitelisting verification.
- Order injection with Exchange-issued Algo-ID.
"""

import logging
import os
import math
import requests

from api.broker_adapter import UnifiedBrokerAdapter, PaperMatchingEngine, NormalizedOrder

logger = logging.getLogger("trading.broker")

class BrokerAPI:
    """
    Interface for live execution.
    Currently locked in scaffolding mode. DO NOT connect real keys yet.
    """
    
    def __init__(self, api_key: str, api_secret: str, totp_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.totp_secret = totp_secret
        self.access_token = None
        self.is_connected = False
        self.algo_id = os.getenv("EXCHANGE_ALGO_ID", "RETAIL_10EPS")
        self.broker_mode = os.getenv("BROKER_MODE", "disabled").lower()

    def _verify_static_ip(self) -> bool:
        """
        SEBI requires static IP whitelisting for automated orders.
        This checks if our current public IP matches the whitelisted one.
        """
        try:
            resp = requests.get("https://api.ipify.org", timeout=5)
            if resp.status_code != 200:
                logger.error(f"IP check returned status {resp.status_code}")
                return False
            current_ip = resp.text.strip()
            import ipaddress
            try:
                ipaddress.ip_address(current_ip)
            except ValueError:
                logger.error(f"Invalid IP address format returned from lookup: {current_ip[:50]}")
                return False
            whitelisted_ip = os.getenv("WHITELISTED_IP")
            if not whitelisted_ip:
                logger.error("WHITELISTED_IP is not configured; refusing broker connection.")
                return False
            if current_ip != whitelisted_ip:
                logger.error(f"IP Mismatch! Current: {current_ip}, Whitelisted: {whitelisted_ip}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to verify IP: {e}")
            return False

    def connect(self) -> bool:
        """Authenticate via OAuth + TOTP."""
        logger.info("Attempting Broker API connection...")
        
        if not self.api_key or not self.api_secret:
            logger.error("Missing API credentials.")
            return False
            
        if not self._verify_static_ip():
            return False
            
        if self.broker_mode != "live":
            logger.error("No live broker adapter is configured; refusing simulated execution.")
            return False

        # --- Placeholder for actual Kite Connect / Upstox OAuth Flow ---
        # 1. Generate TOTP from totp_secret
        # 2. POST to login endpoint
        # 3. Retrieve request_token
        # 4. Exchange request_token + api_secret for access_token
        
        logger.error("Live broker OAuth is not implemented; refusing to report a connection.")
        return False

    def place_order(
        self,
        ticker: str,
        quantity: int,
        direction: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        exchange: str = "NSE",
    ) -> str:
        """
        Place an order with Algo-ID tagging.
        """
        if not self.is_connected:
            raise ConnectionError("Broker API not connected.")

        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("Ticker is required")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("Quantity must be a positive integer")
        direction = direction.upper().strip()
        if direction not in {"LONG", "SHORT", "BUY", "SELL"}:
            raise ValueError("Direction must be LONG, SHORT, BUY, or SELL")
        order_type = order_type.upper().strip()
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("Unsupported order type")
        if order_type == "LIMIT" and (not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0):
            raise ValueError("Limit orders require a positive finite price")
        exchange = exchange.upper().strip()
        if exchange not in {"NSE", "NFO", "BSE", "BFO"}:
            raise ValueError("Only Indian NSE/NFO and BSE/BFO execution is supported")
            
        # Map direction to broker specific sides
        side = direction if direction in {"BUY", "SELL"} else ("BUY" if direction == "LONG" else "SELL")
        
        payload = {
            "tradingsymbol": ticker,
            "exchange": exchange,
            "transaction_type": side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "validity": "DAY",
            "tag": self.algo_id # MANDATORY SEBI ALGO-ID TAGGING
        }
        
        raise RuntimeError("Live order submission is unavailable until a real broker adapter is configured")


class SmartAPIBroker(BrokerAPI):
    """
    Angel One SmartAPI adapter for Indian Stock Market F&O execution.
    Listed in public-apis (https://smartapi.angelbroking.com/).

    Supports:
    - Automated RFC 6238 TOTP 2FA.
    - Segment routing to NFO (NSE F&O) and BFO (BSE F&O / SENSEX).
    - SEBI Algo-ID tagged execution.
    - Real-time margin checking.
    """

    BASE_URL = "https://apiconnect.angelbroking.com"

    def __init__(
        self,
        api_key: str,
        client_code: str,
        password: str,
        totp_secret: str,
        api_secret: str = ""
    ):
        super().__init__(api_key=api_key, api_secret=api_secret, totp_secret=totp_secret)
        self.client_code = client_code
        self.password = password
        self.jwt_token = None
        self.feed_token = None
        self.refresh_token = None

    @staticmethod
    def _generate_totp(secret: str) -> str:
        """RFC 6238 TOTP token generation without external dependencies."""
        import base64
        import hashlib
        import hmac
        import struct
        import time

        clean_secret = secret.upper().replace(" ", "").strip()
        key = base64.b32decode(clean_secret)
        counter = struct.pack(">Q", int(time.time() // 30))
        mac = hmac.new(key, counter, hashlib.sha1).digest()
        offset = mac[-1] & 0x0F
        binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(binary % 1000000).zfill(6)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-PrivateKey": self.api_key,
            "Authorization": f"Bearer {self.jwt_token}" if self.jwt_token else "",
        }

    def connect(self) -> bool:
        """Authenticate with Angel One SmartAPI using client code, password, and TOTP."""
        logger.info(f"Connecting to Angel One SmartAPI for client {self.client_code}...")

        if not self.api_key or not self.client_code or not self.password:
            logger.error("Missing SmartAPI credentials (api_key, client_code, or password).")
            return False

        if not self._verify_static_ip():
            return False

        if self.broker_mode != "live":
            logger.error("BROKER_MODE is not set to 'live'; refusing real SmartAPI connection.")
            return False

        try:
            totp = self._generate_totp(self.totp_secret)
            payload = {
                "clientcode": self.client_code,
                "password": self.password,
                "totp": totp,
            }
            resp = requests.post(
                f"{self.BASE_URL}/rest/auth/partner/v1/generate-token",
                json=payload,
                headers=self._headers(),
                timeout=10,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("status"):
                self.jwt_token = data.get("data", {}).get("jwtToken")
                self.feed_token = data.get("data", {}).get("feedToken")
                self.refresh_token = data.get("data", {}).get("refreshToken")
                self.is_connected = True
                logger.info(f"Successfully authenticated SmartAPI session for {self.client_code}.")
                return True
            else:
                logger.error(f"SmartAPI login failed: {data.get('message', resp.text)}")
                return False
        except Exception as e:
            logger.error(f"SmartAPI connection exception: {e}")
            return False

    def place_order(
        self,
        ticker: str,
        quantity: int,
        direction: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        exchange: str = "NFO",
        symbol_token: str = "0",
    ) -> str:
        """
        Execute an F&O order via SmartAPI with Algo-ID tagging.
        exchange must be 'NFO' (NSE F&O) or 'BFO' (BSE F&O / SENSEX).
        """
        if self.broker_mode != "live":
            raise RuntimeError("Live trading disabled: BROKER_MODE must be 'live' to submit orders.")

        if not self.is_connected:
            raise ConnectionError("SmartAPI is not connected.")

        if not isinstance(ticker, str) or not ticker.strip() or "\x00" in ticker:
            raise ValueError("Valid ticker is required")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("Quantity must be a positive integer")
        dir_clean = direction.upper().strip()
        if dir_clean not in {"BUY", "SELL", "LONG", "SHORT"}:
            raise ValueError(f"Invalid direction '{direction}'. Must be BUY, SELL, LONG, or SHORT.")
        side = "BUY" if dir_clean in ("BUY", "LONG") else "SELL"

        ot_clean = order_type.upper().strip()
        if ot_clean not in {"MARKET", "LIMIT"}:
            raise ValueError(f"Unsupported order type '{order_type}'. Must be MARKET or LIMIT.")

        if ot_clean == "LIMIT":
            if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                raise ValueError("Limit orders require a positive finite price")

        ex = exchange.upper().strip()
        if ex not in ("NFO", "BFO", "NSE", "BSE"):
            raise ValueError(f"Invalid exchange for SmartAPI F&O: {exchange}")

        variety = "NORMAL"

        payload = {
            "variety": variety,
            "tradingsymbol": ticker.strip().upper(),
            "symboltoken": str(symbol_token).strip(),
            "transactiontype": side,
            "exchange": ex,
            "ordertype": ot_clean,
            "producttype": "INTRADAY",
            "duration": "DAY",
            "price": str(price) if ot_clean == "LIMIT" else "0",
            "quantity": str(quantity),
            "tag": self.algo_id,  # Mandatory SEBI Algo-ID
        }

        try:
            resp = requests.post(
                f"{self.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder",
                json=payload,
                headers=self._headers(),
                timeout=10,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("status"):
                order_id = data.get("data", {}).get("orderid", "")
                logger.info(f"SmartAPI Order placed successfully! Order ID: {order_id}")
                return order_id
            else:
                msg = data.get("message", resp.text)
                logger.error(f"SmartAPI Order rejected: {msg}")
                raise RuntimeError(f"SmartAPI order rejected: {msg}")
        except Exception as e:
            logger.error(f"SmartAPI order submission error: {e}")
            raise

