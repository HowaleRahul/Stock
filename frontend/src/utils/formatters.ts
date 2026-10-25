/**
 * Indian Financial Currency & Number Formatting Utilities
 * Compliant with Indian Numbering System (Lakhs & Crores) and SEBI/NSE trading standards.
 */

export interface CurrencyFormatOptions {
  showSign?: boolean;
  decimals?: number;
  useParenthesesForNegative?: boolean;
}

/**
 * Formats a numerical value into standard Indian Financial Currency representation.
 * - Positive: ₹2,50,000.00
 * - Negative: -₹5,000.00 (or +₹5,000.00 if showSign is true)
 * - Zero: ₹0.00
 */
export const formatIndianCurrency = (
  amount: number | string | undefined | null,
  options: CurrencyFormatOptions = {}
): string => {
  const num = Number(amount);
  if (!Number.isFinite(num)) {
    return '₹0.00';
  }

  const decimals = options.decimals !== undefined ? options.decimals : 2;
  const absVal = Math.abs(num).toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  if (num < 0) {
    return `-₹${absVal}`;
  }
  if (options.showSign && num > 0) {
    return `+₹${absVal}`;
  }
  return `₹${absVal}`;
};

/**
 * Formats standard numbers with Indian grouping (e.g. 10,00,000).
 */
export const formatIndianNumber = (
  val: number | string | undefined | null,
  decimals = 0
): string => {
  const num = Number(val);
  if (!Number.isFinite(num)) {
    return '0';
  }
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};
