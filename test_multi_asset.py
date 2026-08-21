import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from ml.continuous_trainer import generate_features_for_ticker

def test_crypto():
    print("\n--- Testing CRYPTO (BTC-USD) ---")
    tf_config = {"tf": "1d", "period": "6mo", "tp_atr": 3.0, "sl_atr": 1.5, "max_hold": 20}
    X, y = generate_features_for_ticker("BTC-USD", tf_config, "CRYPTO")
    
    if X is not None:
        print(f"Success! Generated {len(X)} rows for Crypto.")
        print(f"feat_is_crypto average: {X['feat_is_crypto'].mean()}")
        print(f"feat_is_in_equity average: {X['feat_is_in_equity'].mean()}")
    else:
        print("Failed to generate features for Crypto.")

def test_us_equity():
    print("\n--- Testing US EQUITY (^GSPC) ---")
    tf_config = {"tf": "1d", "period": "6mo", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 20}
    X, y = generate_features_for_ticker("^GSPC", tf_config, "US_EQUITY")
    
    if X is not None:
        print(f"Success! Generated {len(X)} rows for US Equity.")
        print(f"feat_is_us_equity average: {X['feat_is_us_equity'].mean()}")
    else:
        print("Failed to generate features for US Equity.")

if __name__ == "__main__":
    test_crypto()
    test_us_equity()
