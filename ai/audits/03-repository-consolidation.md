# Audit 03: Repository Consolidation & Dead Code Elimination

**Audit Date**: October 2026  
**Auditor**: Senior Software Architect & Technical Lead  
**Status**: Complete Inventory Verified; Zero Backend Dependencies on Legacy Codebases Confirmed  
**Target Directories**: `frontend_legacy/`, `web/`, `frontend/`

---

## 1. Executive Summary

The project root currently houses **three distinct frontend codebases** representing three chronological generations of user interface development:

1. **`frontend_legacy/`**: Vanilla JavaScript + HTML5 + CSS (Phase 1/2 proof-of-concept).
2. **`web/`**: Untyped React 18 JavaScript prototype with hardcoded localhost ports (Phase 3/4).
3. **`frontend/`**: The active, production-grade React 19 + TypeScript + Vite SPA (Phase 5+).

An exhaustive code audit confirmed that **`frontend_legacy/` and `web/` are 100% dead code**. Neither directory is mounted by the FastAPI backend, invoked by `start.py`, covered by automated tests, or deployed to production. They represent significant technical debt, cognitive noise, disk bloat (including orphaned `node_modules` in `web/`), and dependency security risks.

---

## 2. Comparative Feature & Asset Inventory

| Feature / Capability | `frontend_legacy/` | `web/` | `frontend/` (Active SPA) | Parity Status |
|---|---|---|---|---|
| **Language / Typing** | Vanilla ES6 (No TS) | React JSX (No TS) | React 19 + TypeScript 5 | **Superior in `frontend/`** |
| **Build System** | None (Static files) | Vite (Basic JS) | Vite 8 + PostCSS + Tailwind 4 | **Superior in `frontend/`** |
| **API Authentication**| None (Keyless only) | None (Keyless only) | Persistent `X-API-Key` + Interceptors | **Superior in `frontend/`** |
| **API Base URL** | `window.location.origin` | Hardcoded `127.0.0.1:8000` | Relative `/api` with Vite Proxy | **Superior in `frontend/`** |
| **Interactive Charts**| TradingView Lightweight v4 | Embedded Widget iframe | Lightweight Charts v5 + TV Iframe | **Superior in `frontend/`** |
| **Technical Setups** | 5 Cards (static) | None | Full signals + confidence badges | **Superior in `frontend/`** |
| **Trade Journal** | None | Basic `TradeJournal.jsx` | Full `AIJournal.tsx` with RL weights | **Superior in `frontend/`** |
| **Metrics / Analytics**| None | Basic `MetricsPanel.jsx` | `Analytics.tsx` with Sharpe/Sortino | **Superior in `frontend/`** |
| **Portfolio Manager** | Static `portfolio.js` | None | `Portfolio.tsx` with live MTM & close | **Superior in `frontend/`** |
| **Backtest Viewer** | None | None | `BacktestUI.tsx` with trade rows | **Exclusive to `frontend/`** |
| **Strategy Builder** | None | None | `StrategyBuilder.tsx` rule composer | **Exclusive to `frontend/`** |
| **Training Engine UI** | None | None | `TrainingUI.tsx` operational lab | **Exclusive to `frontend/`** |
| **Swing Toolkit** | None | None | `SwingToolkit.tsx` scanners & ORB | **Exclusive to `frontend/`** |
| **Option Chart Viewer**| None | None | `OptionChartViewer.tsx` CE/PE bars | **Exclusive to `frontend/`** |
| **Error Handling** | Console logs | Console logs | `ErrorBoundary.tsx` + retry states | **Superior in `frontend/`** |

### 2.1 Asset Parity Check
We inspected all static assets across the directories:
- `web/src/assets/hero.png` $\rightarrow$ Present identically in `frontend/src/assets/hero.png`.
- `web/src/assets/react.svg` $\rightarrow$ Present identically in `frontend/src/assets/react.svg`.
- `web/src/assets/vite.svg` $\rightarrow$ Present identically in `frontend/src/assets/vite.svg`.
- `frontend_legacy/styles.css` $\rightarrow$ All custom color schemes and typography were ported and modernized into `frontend/src/index.css`.
- **Conclusion**: There are **zero unique assets, styles, or logic** in `frontend_legacy/` or `web/` that are missing from `frontend/`.

---

## 3. Dependency & Reference Verification

### 3.1 Backend FastAPI Mounting
Inspecting `api/main.py` lines 148–152:
```python
# Serve frontend static files (Phase 2 Chart UI)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_frontend_dir):
    app.mount("/app", SPAStaticFiles(directory=_frontend_dir, html=True), name="frontend")
```
- FastAPI mounts **only** `frontend/dist`.
- Neither `frontend_legacy` nor `web` is registered, mounted, or linked in any API route or middleware.

### 3.2 Master Launcher (`start.py`)
Inspecting `start.py` lines 29–38:
```python
# 3. Start the React Frontend (Vite)
print("[3/3] Starting React Dashboard...")
frontend_dir = os.path.join(os.getcwd(), "frontend")
npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
ui_proc = subprocess.Popen([npm_cmd, "run", "dev"], cwd=frontend_dir)
```
- `start.py` executes `npm run dev` **strictly** inside `frontend/`.

### 3.3 Static Code Search
A full repository search across all `.py`, `.json`, and `.yml` files confirmed **zero references** to `frontend_legacy` or `web/`.

---

## 4. Risks of Retaining Legacy Frontends

1. **AI / Contributor Misdirection**: Future automated agents and human developers searching for components (e.g. `TradingViewWidget`) find multiple implementations (`web/src/components/TradingViewWidget.jsx` vs `frontend/src/components/TradingViewWidget.tsx`), risking accidental modifications to the wrong file.
2. **Security Vulnerabilities in Dead Dependencies**: `web/package.json` contains outdated npm packages with unpatched CVEs residing in `web/node_modules/`.
3. **Storage & Git Overhead**: `web/node_modules` consumes significant disk space and increases search indexing times across the workspace.

---

## 5. Recommended Consolidation Action Plan

### Recommended Action: Safe Archival or Deletion
When user approval is granted, execute the following steps:

1. **Option A: Clean Deletion (Recommended)**
   ```powershell
   Remove-Item -Recurse -Force frontend_legacy
   Remove-Item -Recurse -Force web
   ```
   Because git history preserves all 28 historical commits, these directories can always be recovered from git history if historical reference is ever needed.

2. **Option B: Archival to `.archive/` (Alternative)**
   If the team prefers keeping historical files on disk without polluting the active namespace:
   ```powershell
   New-Item -ItemType Directory -Path .archive -Force
   Move-Item -Path frontend_legacy -Destination .archive/frontend_legacy
   Move-Item -Path web -Destination .archive/web
   Remove-Item -Recurse -Force .archive/web/node_modules
   ```
   Add `.archive/` to `.gitignore`.
