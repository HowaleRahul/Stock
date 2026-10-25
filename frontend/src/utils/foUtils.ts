/**
 * Indian F&O (Futures & Options) Market Utilities
 * Standardized for NSE (National Stock Exchange) and BSE (Bombay Stock Exchange) specifications.
 */

export interface Greeks {
  delta: number;
  theta: number; // ₹/day
  gamma: number;
  vega: number;  // ₹ / 1% IV change
  iv: number;    // % Implied Volatility
}

/**
 * Official NSE / BSE Index Derivatives Lot Sizes
 */
export const EXCHANGE_LOT_SIZES: Record<string, number> = {
  NIFTY: 25,
  BANKNIFTY: 15,
  SENSEX: 10,
  FINNIFTY: 25,
  MIDCPNIFTY: 50,
  BANKEX: 15,
  RELIANCE: 250,
  HDFCBANK: 550,
  ICICIBANK: 700,
  INFY: 400,
  TCS: 175,
};

/**
 * Returns exchange lot size for given underlying symbol.
 */
export const getExchangeLotSize = (symbol: string): number => {
  const clean = symbol.toUpperCase().replace(/\^/g, '').replace(/\.NS/g, '').replace(/\.BO/g, '');
  if (EXCHANGE_LOT_SIZES[clean]) {
    return EXCHANGE_LOT_SIZES[clean];
  }
  if (clean.includes('BANKNIFTY') || clean.includes('NSEBANK')) return 15;
  if (clean.includes('SENSEX') || clean.includes('BSESN')) return 10;
  if (clean.includes('MIDCP') || clean.includes('MIDCAP')) return 50;
  if (clean.includes('FINNIFTY')) return 25;
  if (clean.includes('NIFTY') || clean.includes('NSEI')) return 25;
  return 25; // Default standard lot
};

/**
 * Formats canonical Indian F&O contract symbol:
 * Examples:
 *  - "NIFTY 24500 CE"
 *  - "BANKNIFTY 52000 PE"
 *  - "SENSEX 80000 CE"
 *  - "NIFTY FUT"
 */
export const formatContractSymbol = (
  underlying: string,
  strike?: number | string | null,
  optType?: 'CE' | 'PE' | string | null,
  instrumentType?: 'OPTION' | 'FUTURES' | 'FUT' | string | null
): string => {
  let cleanUnderlying = underlying.toUpperCase().trim()
    .replace(/\^/g, '')
    .replace(/\.NS/g, '')
    .replace(/\.BO/g, '');

  if (cleanUnderlying === 'NSEI') cleanUnderlying = 'NIFTY';
  if (cleanUnderlying === 'NSEBANK') cleanUnderlying = 'BANKNIFTY';
  if (cleanUnderlying === 'BSESN') cleanUnderlying = 'SENSEX';

  const isFut = instrumentType === 'FUTURES' || instrumentType === 'FUT' || (!optType && !strike && underlying.includes('FUT'));
  if (isFut) {
    return `${cleanUnderlying} FUT`;
  }

  if (strike && optType) {
    const cleanType = String(optType).toUpperCase().includes('PUT') || String(optType).toUpperCase() === 'PE' ? 'PE' : 'CE';
    return `${cleanUnderlying} ${strike} ${cleanType}`;
  }

  return cleanUnderlying;
};

/**
 * Computes current Indian Standard Time (IST = UTC + 5:30)
 */
export const getISTDate = (date: Date = new Date()): Date => {
  const utc = date.getTime() + (date.getTimezoneOffset() * 60000);
  const istOffset = 5.5 * 60 * 60 * 1000;
  return new Date(utc + istOffset);
};

export interface MarketSessionState {
  status: 'PRE_OPEN' | 'LIVE' | 'CLOSED' | 'WEEKEND';
  badgeTitle: string;
  subText: string;
  nextExpiry: string;
  expiryName: string;
  expiryCountdown: string;
  istTimeString: string;
  isOpen: boolean;
}

/**
 * Real-time Indian Market Session Evaluator & Expiry Countdown
 * - IST: Regular 09:15 - 15:30
 * - Pre-Open: 09:00 - 09:15
 * - Expiry cycle: Tue=FINNIFTY, Wed=BANKNIFTY, Thu=NIFTY, Fri=SENSEX (at 15:30 IST)
 */
export const getMarketSessionState = (now: Date = new Date()): MarketSessionState => {
  const ist = getISTDate(now);
  const day = ist.getDay(); // 0 = Sun, 1 = Mon, ..., 6 = Sat
  const hours = ist.getHours();
  const minutes = ist.getMinutes();
  const totalMins = hours * 60 + minutes;

  const isWeekend = day === 0 || day === 6;
  const isPreOpen = !isWeekend && totalMins >= 540 && totalMins < 555; // 09:00 - 09:15 IST
  const isLive = !isWeekend && totalMins >= 555 && totalMins < 930;    // 09:15 - 15:30 IST

  let status: 'PRE_OPEN' | 'LIVE' | 'CLOSED' | 'WEEKEND' = 'CLOSED';
  let badgeTitle = 'F&O MARKET CLOSED';
  let subText = 'Opens 09:00 IST';

  if (isWeekend) {
    status = 'WEEKEND';
    badgeTitle = 'WEEKEND (CLOSED)';
    subText = 'Opens Mon 09:00 IST';
  } else if (isPreOpen) {
    status = 'PRE_OPEN';
    badgeTitle = 'NSE PRE-OPEN';
    const left = 555 - totalMins;
    subText = `Regular opens in ${left}m`;
  } else if (isLive) {
    status = 'LIVE';
    badgeTitle = 'INDIAN F&O LIVE';
    const closeLeftMins = 930 - totalMins;
    const h = Math.floor(closeLeftMins / 60);
    const m = closeLeftMins % 60;
    subText = `Closes in ${h > 0 ? `${h}h ` : ''}${m}m`;
  }

  // Weekly index expiry cycle (all expire at 15:30 IST)
  const expiries = [
    { name: 'FINNIFTY', day: 2 },
    { name: 'BANKNIFTY', day: 3 },
    { name: 'NIFTY', day: 4 },
    { name: 'SENSEX', day: 5 },
  ];

  let nextExpiryObj: { name: string; diffMs: number } | null = null;
  let minDiffMs = Infinity;

  for (const exp of expiries) {
    let daysAhead = (exp.day - day + 7) % 7;
    const target = new Date(ist);
    target.setDate(ist.getDate() + daysAhead);
    target.setHours(15, 30, 0, 0);

    if (daysAhead === 0 && totalMins >= 930) {
      target.setDate(target.getDate() + 7);
    }

    const diff = target.getTime() - ist.getTime();
    if (diff > 0 && diff < minDiffMs) {
      minDiffMs = diff;
      nextExpiryObj = { name: exp.name, diffMs: diff };
    }
  }

  let expiryCountdown = '';
  let expiryName = 'NIFTY';
  if (nextExpiryObj) {
    expiryName = nextExpiryObj.name;
    const totalSecs = Math.floor(nextExpiryObj.diffMs / 1000);
    const d = Math.floor(totalSecs / 86400);
    const h = Math.floor((totalSecs % 86400) / 3600);
    const m = Math.floor((totalSecs % 3600) / 60);
    expiryCountdown = `${d > 0 ? `${d}d ` : ''}${h}h ${m}m`;
  }

  return {
    status,
    badgeTitle,
    subText,
    nextExpiry: `${expiryName} (${expiryCountdown})`,
    expiryName,
    expiryCountdown,
    istTimeString: ist.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }),
    isOpen: isLive,
  };
};

/**
 * Option Payoff & Risk Profile specifications for Indian F&O Trading.
 */
export interface OptionPayoffProfile {
  strategyName: string;
  isCredit: boolean;
  isSeller: boolean;
  action: 'BUY' | 'SELL';
  breakeven: number;
  breakevenPoints: number[];
  maxProfit: number;
  maxLoss: number;
  riskRewardRatio: number | null;
  netPremium: number;
  marginEstimated: number;
  thetaFormatted: string;
  thetaIsPositiveForTrader: boolean;
  safetyBufferPct?: number;
}

/**
 * Checks whether an Indian F&O position or trade recommendation is an Option Selling,
 * Credit Spread, or Hedged Writing strategy.
 */
export const isOptionSellingOrSpread = (item: any): boolean => {
  if (!item) return false;
  const action = String(item.action || '').toUpperCase();
  const dir = String(item.direction || '').toUpperCase();
  const strat = String(item.strategy_type || item.strategy || '').toUpperCase();
  const inst = String(item.instrument_type || '').toUpperCase();
  const optType = String(item.option_type || item.opt_type || '').toUpperCase();

  if (action === 'SELL') return true;
  if (
    strat.includes('CREDIT') ||
    strat.includes('SPREAD') ||
    strat.includes('WRITING') ||
    strat.includes('BULL_PUT') ||
    strat.includes('BEAR_CALL') ||
    strat.includes('IRON_CONDOR')
  ) {
    return true;
  }
  if (inst === 'SPREAD') return true;
  if ((dir === 'SHORT' || dir === 'SELL') && (inst === 'OPTION' || optType === 'CE' || optType === 'PE')) {
    return true;
  }
  return false;
};

/**
 * Returns canonical readable strategy classification for F&O positions and trades.
 */
export const getOptionStrategyLabel = (item: any): string => {
  if (!item) return 'Directional';
  const strat = String(item.strategy_type || item.strategy || '').toUpperCase();
  const action = String(item.action || '').toUpperCase();
  const dir = String(item.direction || '').toUpperCase();
  const optType = String(item.option_type || item.opt_type || '').toUpperCase();

  if (strat.includes('BULL_PUT') || strat === 'BULL_PUT_SPREAD') return 'Bull Put Credit Spread';
  if (strat.includes('BEAR_CALL') || strat === 'BEAR_CALL_SPREAD') return 'Bear Call Credit Spread';
  if (strat.includes('CREDIT_SPREAD')) return 'Credit Spread';
  if (strat.includes('HEDGED_WRITING') || strat.includes('WRITING')) return 'Hedged Writing';
  if (strat.includes('IRON_CONDOR')) return 'Iron Condor';

  const isSeller = action === 'SELL' || dir === 'SHORT' || dir === 'SELL';
  if (isSeller) {
    if (optType === 'CE') return 'Short Call Writing (CE)';
    if (optType === 'PE') return 'Short Put Writing (PE)';
    return 'Option Selling (Short)';
  }

  if (optType === 'CE') return 'Long Call (CE)';
  if (optType === 'PE') return 'Long Put (PE)';
  return 'Long Option';
};

/**
 * Calculates accurate Breakeven, Payoff, and Greek Theta Notation for Option Buying,
 * Option Selling, Credit Spreads, and Hedged Writing.
 */
export const calculateOptionPayoffProfile = (params: {
  underlying: string;
  strike: number;
  optionType: 'CE' | 'PE' | string;
  entryPrice: number;
  currentSpot?: number;
  action?: 'BUY' | 'SELL';
  strategyType?: string;
  hedgeStrike?: number;
  hedgePrice?: number;
  lotSize?: number;
  quantity?: number;
  rawTheta?: number;
}): OptionPayoffProfile => {
  const {
    underlying,
    strike,
    optionType,
    entryPrice,
    currentSpot = strike,
    action = 'BUY',
    strategyType = 'DIRECTIONAL',
    hedgeStrike,
    hedgePrice = 0,
    lotSize = getExchangeLotSize(underlying),
    quantity,
    rawTheta = -12.5,
  } = params;

  const totalQty = quantity && quantity > 0 ? quantity : lotSize;
  const isCE = String(optionType).toUpperCase().includes('CE') || String(optionType).toUpperCase().includes('CALL');
  const isSpread = strategyType.toUpperCase().includes('SPREAD') || Boolean(hedgeStrike);
  const isSeller = action === 'SELL' || strategyType.toUpperCase().includes('CREDIT') || strategyType.toUpperCase().includes('WRITING');

  let strategyName = 'Long Option';
  let isCredit = false;
  let breakeven = strike;
  let maxProfit = 0;
  let maxLoss = 0;
  let netPremium = entryPrice;
  let marginEstimated = entryPrice * totalQty;

  const interval = (underlying === 'BANKNIFTY' || underlying === 'SENSEX') ? 100 : (underlying === 'MIDCPNIFTY' ? 25 : 50);

  if (isSpread || strategyType.toUpperCase().includes('CREDIT')) {
    isCredit = true;
    const soldPrice = entryPrice;
    const boughtPrice = hedgePrice || Math.max(1, entryPrice * 0.25);
    const credit = Math.max(0.1, soldPrice - boughtPrice);
    netPremium = credit;

    if (!isCE || strategyType.toUpperCase().includes('BULL_PUT')) {
      // Bull Put Credit Spread: Sell Higher Put Strike, Buy Lower Put Strike Hedge
      strategyName = 'Bull Put Credit Spread';
      const actualHedgeStrike = hedgeStrike || (strike - interval);
      const width = Math.abs(strike - actualHedgeStrike);
      breakeven = strike - credit;
      maxProfit = credit * totalQty;
      maxLoss = Math.max(0, (width - credit) * totalQty);
      // Hedged spread margin with exchange relief is approximately the spread width * qty
      marginEstimated = width * totalQty;
    } else {
      // Bear Call Credit Spread: Sell Lower Call Strike, Buy Higher Call Strike Hedge
      strategyName = 'Bear Call Credit Spread';
      const actualHedgeStrike = hedgeStrike || (strike + interval);
      const width = Math.abs(actualHedgeStrike - strike);
      breakeven = strike + credit;
      maxProfit = credit * totalQty;
      maxLoss = Math.max(0, (width - credit) * totalQty);
      marginEstimated = width * totalQty;
    }
  } else if (isSeller) {
    isCredit = true;
    netPremium = entryPrice;
    maxProfit = entryPrice * totalQty;
    // Naked index option margin per NSE SPAN ~ 15% of spot value
    marginEstimated = Math.max(85000, currentSpot * totalQty * 0.12);

    if (isCE) {
      strategyName = 'Short Call (CE Writing)';
      breakeven = strike + entryPrice;
      // Max loss theoretically uncapped; practical risk capped at 2.5x premium SL
      maxLoss = entryPrice * 2.5 * totalQty;
    } else {
      strategyName = 'Short Put (PE Writing)';
      breakeven = strike - entryPrice;
      maxLoss = Math.max(0, (strike - entryPrice) * totalQty);
    }
  } else {
    // Option Buyer (Debit)
    isCredit = false;
    netPremium = entryPrice;
    maxLoss = entryPrice * totalQty;
    marginEstimated = entryPrice * totalQty;

    if (isCE) {
      strategyName = 'Long Call (CE)';
      breakeven = strike + entryPrice;
      maxProfit = Math.max(entryPrice * 3 * totalQty, (currentSpot * 1.05 - strike) * totalQty);
    } else {
      strategyName = 'Long Put (PE)';
      breakeven = strike - entryPrice;
      maxProfit = Math.max(entryPrice * 3 * totalQty, (strike - currentSpot * 0.95) * totalQty);
    }
  }

  const rrRatio = maxLoss > 0 ? Number((maxProfit / maxLoss).toFixed(2)) : null;

  // Theta representation: For Sellers and Credit Spreads, theta time decay is PROFIT (+₹/day)!
  // For Buyers, theta decay is a daily COST (-₹/day).
  const absTheta = Math.abs(rawTheta);
  const thetaFormatted = isSeller
    ? `+₹${absTheta.toFixed(2)}/day`
    : `-₹${absTheta.toFixed(2)}/day`;

  // Safety buffer: % distance between current spot and breakeven
  const safetyBufferPct = currentSpot > 0
    ? Math.abs(((currentSpot - breakeven) / currentSpot) * 100)
    : 0;

  return {
    strategyName,
    isCredit,
    isSeller,
    action: isSeller ? 'SELL' : 'BUY',
    breakeven: Number(breakeven.toFixed(2)),
    breakevenPoints: [Number(breakeven.toFixed(2))],
    maxProfit: Number(maxProfit.toFixed(2)),
    maxLoss: Number(maxLoss.toFixed(2)),
    riskRewardRatio: rrRatio,
    netPremium: Number(netPremium.toFixed(2)),
    marginEstimated: Number(marginEstimated.toFixed(2)),
    thetaFormatted,
    thetaIsPositiveForTrader: isSeller,
    safetyBufferPct: Number(safetyBufferPct.toFixed(2)),
  };
};

