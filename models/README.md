# Meta-Ensemble & Explainability Models (`/models`)

## Responsibilities
- **Signal Aggregation:** Combine independent setup confidence scores (`TrendPullback`, `Breakout`, `MeanReversion`, `OptionsFlow`) into a single actionable trade recommendation (`Strong Buy`, `Buy`, `Neutral`, `Sell`, `Strong Sell`).
- **Trainable Weights:** Logistic Regression, Gradient Boosted Trees (`XGBoost`/`LightGBM`), or Reinforcement Learning models trained on historical setup accuracy per regime (trending vs. sideways).
- **Explainability Engine:** Every prediction outputs exact weight attributions using **SHAP values** or linear weight decomposition so the user understands *why* a trade was recommended (e.g., *"Bullish score +0.68 driven by Options Flow (+0.45) and Trend Pullback (+0.30)"*).
- **Online Adaptation:** Periodic weight updates driven by live paper-trading results (Phase 5).

## Roadmap Status
- **Phase 0:** Directory initialized, models to be implemented in Phase 3.
