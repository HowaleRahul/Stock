import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from api.db import async_session_factory, engine, Base
from models.models import Account, JournalEvent, Trade, TradeContext


async def ensure_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def _timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def load_account(default_capital: float) -> Dict[str, Any]:
    async with async_session_factory() as session:
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


async def save_account(account_data: Dict[str, Any]) -> None:
    async with async_session_factory() as session:
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


async def load_open_trades() -> List[Dict[str, Any]]:
    async with async_session_factory() as session:
        rows = (await session.execute(select(Trade).where(Trade.is_open.is_(True)))).scalars().all()
        contexts = {
            context.order_id: json.loads(context.payload)
            for context in (await session.execute(select(TradeContext))).scalars().all()
        }
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


async def open_trade(trade_data: Dict[str, Any]) -> None:
    order_id = str(trade_data['id'])
    async with async_session_factory() as session:
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


async def update_trade(trade_data: Dict[str, Any]) -> None:
    order_id = str(trade_data['id'])
    async with async_session_factory() as session:
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


async def save_journal_event(record: Dict[str, Any]) -> None:
    async with async_session_factory() as session:
        session.add(JournalEvent(
            event=record.get('event', 'UNKNOWN'),
            trade_id=record.get('trade_id'),
            timestamp=_timestamp(record.get('timestamp')),
            payload=json.dumps(record, default=str),
        ))
        await session.commit()


async def persist_portfolio(
    account_data: Dict[str, Any],
    trades: List[Dict[str, Any]],
    journal_events: Optional[List[Dict[str, Any]]] = None,
) -> None:
    async with async_session_factory() as session:
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

        for trade_data in trades:
            order_id = str(trade_data['id'])
            row = (await session.execute(
                select(Trade).where(Trade.order_id == order_id)
            )).scalar_one_or_none()
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
            else:
                row.is_open = trade_data.get('status') == 'OPEN'
                row.exit_price = trade_data.get('exit_price')
                row.pnl_pct = (trade_data.get('pnl_pct') or 0.0) * 100 if trade_data.get('pnl_pct') is not None else None
                row.exit_time = _timestamp(trade_data.get('closed_at')) if trade_data.get('closed_at') else None

            context = (await session.execute(
                select(TradeContext).where(TradeContext.order_id == order_id)
            )).scalar_one_or_none()
            payload = json.dumps(trade_data, default=str)
            if context is None:
                session.add(TradeContext(order_id=order_id, payload=payload))
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