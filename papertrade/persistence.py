import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from api.db import async_session_factory, engine, Base
from models.models import Account, JournalEvent, Trade, TradeContext

logger = logging.getLogger("trading.papertrade.persistence")


async def ensure_schema() -> None:
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:
        logger.warning(f"Database ensure_schema failed: {exc}; proceeding in offline disk mode.")


def _timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError, AttributeError):
        return datetime.now(timezone.utc)


async def load_account(default_capital: float) -> Dict[str, Any]:
    try:
        async with async_session_factory() as session:
            try:
                account = (await session.execute(select(Account).order_by(Account.id))).scalars().first()
                if account is None:
                    account = Account(capital=default_capital, peak_capital=default_capital, status='ACTIVE')
                    session.add(account)
                    await session.commit()
                return {
                    'capital': account.capital,
                    'peak_capital': account.peak_capital,
                    'status': account.status,
                }
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in load_account: {exc}; falling back to disk.")
        if os.path.exists("paper_account.json"):
            import time
            for attempt in range(5):
                try:
                    with open("paper_account.json", "r", encoding="utf-8") as f:
                        return json.load(f)
                except (PermissionError, OSError):
                    time.sleep(0.02 * (attempt + 1))
                except Exception:
                    break
        return {'capital': default_capital, 'peak_capital': default_capital, 'status': 'ACTIVE'}


async def save_account(account_data: Dict[str, Any]) -> None:
    try:
        async with async_session_factory() as session:
            try:
                account = (await session.execute(select(Account).order_by(Account.id))).scalars().first()
                if account is None:
                    account = Account(
                        capital=account_data['capital'],
                        peak_capital=account_data['peak_capital'],
                        status=account_data['status'],
                    )
                    session.add(account)
                else:
                    account.capital = account_data['capital']
                    account.peak_capital = account_data['peak_capital']
                    account.status = account_data['status']
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in save_account: {exc}; fallback handled by disk persistence.")


async def load_open_trades() -> List[Dict[str, Any]]:
    try:
        async with async_session_factory() as session:
            try:
                rows = (await session.execute(select(Trade).where(Trade.is_open.is_(True)))).scalars().all()
                order_ids = [row.order_id for row in rows]
                contexts = {}
                if order_ids:
                    context_rows = (await session.execute(
                        select(TradeContext).where(TradeContext.order_id.in_(order_ids))
                    )).scalars().all()
                    for context in context_rows:
                        try:
                            contexts[context.order_id] = json.loads(context.payload)
                        except Exception:
                            contexts[context.order_id] = {}
                trades = []
                for row in rows:
                    trade = contexts.get(row.order_id, {})
                    trade.update({
                        'id': row.order_id,
                        'ticker': row.ticker,
                        'direction': row.direction,
                        'entry_price': row.entry_price,
                        'quantity': row.quantity,
                        'invested': row.invested,
                        'tp': row.take_profit,
                        'sl': row.stop_loss,
                        'status': 'OPEN',
                    })
                    trades.append(trade)
                return trades
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in load_open_trades: {exc}; falling back to disk.")
        if os.path.exists("paper_trades.json"):
            import time
            for attempt in range(5):
                try:
                    with open("paper_trades.json", "r", encoding="utf-8") as f:
                        raw_trades = json.load(f)
                        return [t for t in raw_trades if t.get("status") == "OPEN"]
                except (PermissionError, OSError):
                    time.sleep(0.02 * (attempt + 1))
                except Exception:
                    break
        return []


async def open_trade(trade_data: Dict[str, Any]) -> None:
    order_id = str(trade_data['id'])
    try:
        async with async_session_factory() as session:
            try:
                row = Trade(
                    order_id=order_id,
                    ticker=trade_data['ticker'],
                    direction=trade_data['direction'],
                    entry_price=trade_data['entry_price'],
                    quantity=trade_data['quantity'],
                    invested=trade_data['invested'],
                    take_profit=trade_data.get('tp'),
                    stop_loss=trade_data.get('sl'),
                    is_open=True,
                    entry_time=_timestamp(trade_data.get('opened_at')),
                )
                session.add(row)
                session.add(TradeContext(order_id=order_id, payload=json.dumps(trade_data, default=str)))
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in open_trade for {order_id}: {exc}; caller will persist to disk.")


async def update_trade(trade_data: Dict[str, Any]) -> None:
    order_id = str(trade_data['id'])
    try:
        async with async_session_factory() as session:
            try:
                row = (await session.execute(select(Trade).where(Trade.order_id == order_id))).scalar_one_or_none()
                if row is None:
                    await open_trade(trade_data)
                    return
                row.is_open = trade_data.get('status') == 'OPEN'
                row.exit_price = trade_data.get('exit_price')
                row.pnl_pct = (trade_data.get('pnl_pct') or 0.0) * 100 if trade_data.get('pnl_pct') is not None else None
                row.exit_time = _timestamp(trade_data.get('closed_at')) if trade_data.get('closed_at') else None
                context = (await session.execute(select(TradeContext).where(TradeContext.order_id == order_id))).scalar_one_or_none()
                if context is None:
                    session.add(TradeContext(order_id=order_id, payload=json.dumps(trade_data, default=str)))
                else:
                    context.payload = json.dumps(trade_data, default=str)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in update_trade for {order_id}: {exc}; caller persists to disk.")


async def save_journal_event(record: Dict[str, Any]) -> None:
    try:
        async with async_session_factory() as session:
            try:
                session.add(JournalEvent(
                    event=record.get('event', 'UNKNOWN'),
                    trade_id=record.get('trade_id'),
                    timestamp=_timestamp(record.get('timestamp')),
                    payload=json.dumps(record, default=str),
                ))
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in save_journal_event: {exc}.")


async def persist_portfolio(
    account_data: Dict[str, Any],
    trades: List[Dict[str, Any]],
    journal_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    try:
        async with async_session_factory() as session:
            try:
                account = (await session.execute(select(Account).order_by(Account.id))).scalars().first()
                if account is None:
                    session.add(Account(
                        capital=account_data['capital'],
                        peak_capital=account_data['peak_capital'],
                        status=account_data['status'],
                    ))
                else:
                    account.capital = account_data['capital']
                    account.peak_capital = account_data['peak_capital']
                    account.status = account_data['status']

                order_ids = [str(trade_data['id']) for trade_data in trades]
                existing_trades_map = {}
                existing_contexts_map = {}
                if order_ids:
                    t_rows = (await session.execute(
                        select(Trade).where(Trade.order_id.in_(order_ids))
                    )).scalars().all()
                    existing_trades_map = {t.order_id: t for t in t_rows}

                    c_rows = (await session.execute(
                        select(TradeContext).where(TradeContext.order_id.in_(order_ids))
                    )).scalars().all()
                    existing_contexts_map = {c.order_id: c for c in c_rows}

                for trade_data in trades:
                    order_id = str(trade_data['id'])
                    row = existing_trades_map.get(order_id)
                    if row is None:
                        row = Trade(
                            order_id=order_id,
                            ticker=trade_data['ticker'],
                            direction=trade_data['direction'],
                            entry_price=trade_data['entry_price'],
                            quantity=trade_data['quantity'],
                            invested=trade_data['invested'],
                            take_profit=trade_data.get('tp'),
                            stop_loss=trade_data.get('sl'),
                            is_open=trade_data.get('status') == 'OPEN',
                            entry_time=_timestamp(trade_data.get('opened_at')),
                        )
                        session.add(row)
                        existing_trades_map[order_id] = row
                    else:
                        row.is_open = trade_data.get('status') == 'OPEN'
                        row.exit_price = trade_data.get('exit_price')
                        row.pnl_pct = (trade_data.get('pnl_pct') or 0.0) * 100 if trade_data.get('pnl_pct') is not None else None
                        row.exit_time = _timestamp(trade_data.get('closed_at')) if trade_data.get('closed_at') else None

                    payload = json.dumps(trade_data, default=str)
                    context = existing_contexts_map.get(order_id)
                    if context is None:
                        context = TradeContext(order_id=order_id, payload=payload)
                        session.add(context)
                        existing_contexts_map[order_id] = context
                    else:
                        context.payload = payload
                for record in journal_events or []:
                    session.add(JournalEvent(
                        event=record.get('event', 'UNKNOWN'),
                        trade_id=record.get('trade_id'),
                        timestamp=_timestamp(record.get('timestamp')),
                        payload=json.dumps(record, default=str),
                    ))
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in persist_portfolio: {exc}; trades & account remain safely saved to disk.")
