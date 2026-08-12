import logging
import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any
from sklearn.linear_model import LogisticRegression
from ml.features import generate_triple_barrier_labels

logger = logging.getLogger("trading.backtest.engine")

class Backtester:
    def __init__(self, fee: float = 0.001, slippage: float = 0.0005, threshold: float = 0.55):
        """
        fee: 0.1% transaction cost per trade
        slippage: 0.05% slippage on entry and exit
        threshold: minimum ML probability required to enter a trade
        """
        self.fee = fee
        self.slippage = slippage
        self.threshold = threshold
        
        # Risk management per user specification
        self.sl_pct = 0.04 # 4% stop loss
        self.tp_pct = 0.10 # 10% take profit

    def run_walk_forward(self, X: pd.DataFrame, df: pd.DataFrame, train_size: int = 120, test_size: int = 20) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        logger.info(f"Starting Real-World walk-forward validation. Total bars: {len(X)}")
        
        equity_curve = []
        positions = []
        benchmark_equity = []
        
        current_equity = 1.0
        current_bench = 1.0
        
        # Real-world state tracking
        in_position = False
        trade_dir = 0 # 1 for Long, -1 for Short
        entry_price = 0.0
        
        # Trade statistics tracking
        trades_won = 0
        trades_lost = 0
        total_trades = 0
        
        # Pre-calculate Triple-Barrier Labels for the entire dataframe to use in training windows
        triple_barrier_labels = generate_triple_barrier_labels(df, tp_pct=self.tp_pct, sl_pct=self.sl_pct, max_hold_bars=20)
        
        for start in range(0, len(X) - train_size - test_size, test_size):
            train_end = start + train_size
            test_end = train_end + test_size
            
            X_train = X.iloc[start:train_end]
            X_test = X.iloc[train_end:test_end]
            
            # Target generation for training: Use Triple-Barrier Labels
            y_train = []
            for i in range(len(X_train)):
                idx = start + i
                label = triple_barrier_labels[idx]
                # If label is 0 (timeout), default to -1 (Loss) or random to force binary class, 
                # but LogisticRegression handles multi-class naturally if 0 is included. 
                # Let's keep it exactly as the triple barrier output.
                y_train.append(label)
                
            model = LogisticRegression(class_weight='balanced', max_iter=1000)
            try:
                model.fit(X_train.values, y_train)
            except ValueError:
                continue
            
            # Test Window execution
            for i in range(len(X_test)):
                idx = train_end + i
                current_bar = df.iloc[idx]
                
                net_ret = 0.0
                
                if in_position:
                    # Evaluate SL / TP
                    hit_exit = False
                    exit_price = 0.0
                    
                    if trade_dir == 1:
                        # Long SL / TP check
                        sl_price = entry_price * (1 - self.sl_pct)
                        tp_price = entry_price * (1 + self.tp_pct)
                        
                        if current_bar['low'] <= sl_price:
                            exit_price = sl_price
                            hit_exit = True
                        elif current_bar['high'] >= tp_price:
                            exit_price = tp_price
                            hit_exit = True
                            
                    elif trade_dir == -1:
                        # Short SL / TP check
                        sl_price = entry_price * (1 + self.sl_pct)
                        tp_price = entry_price * (1 - self.tp_pct)
                        
                        if current_bar['high'] >= sl_price:
                            exit_price = sl_price
                            hit_exit = True
                        elif current_bar['low'] <= tp_price:
                            exit_price = tp_price
                            hit_exit = True
                            
                    if hit_exit:
                        # Calculate exact trade return and close position
                        gross_trade_ret = (exit_price - entry_price) / entry_price if trade_dir == 1 else (entry_price - exit_price) / entry_price
                        # We only apply friction on the entire round-trip (entry + exit)
                        trade_net_ret = gross_trade_ret - (self.fee * 2) - (self.slippage * 2)
                        current_equity *= (1 + trade_net_ret)
                        
                        if trade_net_ret > 0:
                            trades_won += 1
                        else:
                            trades_lost += 1
                            
                        in_position = False
                        trade_dir = 0
                
                else:
                    # Look for new entry
                    features = X_test.iloc[i].values.reshape(1, -1)
                    probs = model.predict_proba(features)[0]
                    classes = list(model.classes_)
                    
                    max_prob = max(probs)
                    if max_prob > self.threshold:
                        pred = classes[list(probs).index(max_prob)]
                        in_position = True
                        trade_dir = pred
                        entry_price = current_bar['close'] # Enter at close
                        total_trades += 1
                
                # Daily Accounting
                equity_curve.append(current_equity)
                positions.append(trade_dir)
                
                # Benchmark (Buy and hold)
                bench_ret = (df['close'].iloc[idx+1] - df['close'].iloc[idx]) / df['close'].iloc[idx]
                current_bench *= (1 + bench_ret)
                benchmark_equity.append(current_bench)

        if not equity_curve:
            return pd.DataFrame(), {}
            
        # Close any open position at end of backtest
        if in_position:
            last_close = df['close'].iloc[train_end + len(X_test) - 1]
            gross_trade_ret = (last_close - entry_price) / entry_price if trade_dir == 1 else (entry_price - last_close) / entry_price
            trade_net_ret = gross_trade_ret - (self.fee * 2) - (self.slippage * 2)
            current_equity *= (1 + trade_net_ret)
            # Update the very last point of equity curve
            equity_curve[-1] = current_equity
            
        results_df = pd.DataFrame({
            "Strategy_Equity": equity_curve,
            "Benchmark_Equity": benchmark_equity,
            "Position": positions
        }, index=df.index[train_size : train_size + len(equity_curve)])
        
        # Calculate Metrics
        strat_returns = results_df["Strategy_Equity"].pct_change().dropna()
        
        # Win Rate is now properly calculated from the discrete trades, not daily bars
        real_win_rate = (trades_won / total_trades) if total_trades > 0 else 0
        
        gross_profits = strat_returns[strat_returns > 0].sum()
        gross_losses = abs(strat_returns[strat_returns < 0].sum())
        profit_factor = gross_profits / gross_losses if gross_losses != 0 else float('inf')
        
        daily_rf = 0.05 / 252 
        excess_returns = strat_returns - daily_rf
        sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252) if excess_returns.std() > 0 else 0
        
        rolling_max = results_df["Strategy_Equity"].cummax()
        drawdown = (results_df["Strategy_Equity"] - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        metrics = {
            "Total_Return": (current_equity - 1.0) * 100,
            "Benchmark_Return": (current_bench - 1.0) * 100,
            "Win_Rate": real_win_rate * 100,
            "Profit_Factor": profit_factor,
            "Sharpe_Ratio": sharpe,
            "Max_Drawdown": max_drawdown * 100,
            "Total_Trades": total_trades
        }
        
        return results_df, metrics
