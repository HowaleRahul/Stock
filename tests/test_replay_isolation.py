import json

from ml.trade_logger import TradeLogger
from ml.reinforcement_learner import ReinforcementLearner


def test_replay_journal_and_rl_state_are_isolated(tmp_path):
    replay_log = tmp_path / "replay.jsonl"
    replay_weights = tmp_path / "setup_weights.json"
    token = TradeLogger.use_log_file(str(replay_log))
    try:
        TradeLogger.log_rejection(
            ticker="TEST.NS",
            direction="LONG",
            reasons=["replay"],
            ai_probability=0.2,
            regime="range-bound",
            config_version="replay_v1",
        )
        assert TradeLogger.get_all_entries() == []
        assert replay_log.exists()
        assert json.loads(replay_log.read_text(encoding="utf-8"))["event"] == "REJECTION"
    finally:
        TradeLogger.reset_log_file(token)

    learner = ReinforcementLearner(weights_file=str(replay_weights))
    learner.update_from_trade(
        setup_signals=[{"name": "TestSetup", "signal": "bullish", "confidence": 0.8}],
        regime="range-bound",
        pnl_pct=0.01,
        is_win=True,
    )
    assert replay_weights.exists()


def test_replay_pending_order_model():
    from ml.replay_engine import ReplayEngine
    engine = ReplayEngine()
    try:
        assert engine._pending_order is None
        # Simulate queuing a pending order
        engine._pending_order = {
            "id": "pending-123",
            "ticker": "TEST.NS",
            "direction": "LONG",
            "quantity": 10,
            "invested": 1000.0,
            "entry_price": 100.0,
            "planned_entry": 100.0,
            "tp": 110.0,
            "sl": 95.0,
        }
        assert engine._pending_order["id"] == "pending-123"
    finally:
        engine.close()