#!/usr/bin/env python3
"""
label_filings.py

Reads an input CSV of flagged filings (must include 'ticker' and 'filingDate'),
computes 1-day and 3-day pct changes around each filing, converts them into
multiclass labels (±1/0), and writes out a labeled CSV.
"""

# --- Imports ---
import pandas as pd
import yfinance as yf
from datetime import timedelta
import argparse

# --- Functions ---
def get_price_changes(ticker: str, filing_date: pd.Timestamp) -> pd.Series:
    """
    Returns a Series with:
      pct_1d: (close_t+1 - close_t-1) / close_t-1
      pct_3d: (close_t+3 - close_t)   / close_t
    around the given filing_date.
    """
    # Download 7 days before through 5 days after
    start = filing_date - timedelta(days=7)
    end   = filing_date + timedelta(days=5)
    hist = yf.download(ticker, start=start, end=end, progress=False)

    # Normalize index to date objects
    dates = [d.date() for d in hist.index]
    if filing_date.date() not in dates:
        return pd.Series([None, None], index=["pct_1d","pct_3d"])

    idx = dates.index(filing_date.date())
    close_prev = hist["Close"].iloc[idx-1]     if idx-1 >= 0         else None
    close_0    = hist["Close"].iloc[idx]       if idx   < len(hist) else None
    close_1d   = hist["Close"].iloc[idx+1]     if idx+1 < len(hist) else None
    close_3d   = hist["Close"].iloc[idx+3]     if idx+3 < len(hist) else None

    pct_1d = ((close_1d - close_prev) / close_prev
              if close_prev and close_1d else None)
    pct_3d = ((close_3d - close_0)    / close_0
              if close_0 and close_3d   else None)

    return pd.Series([pct_1d, pct_3d], index=["pct_1d","pct_3d"])


# --- Main Script ---
def main(input_csv: str, output_csv: str):
    # 1) Load scraper output
    df = pd.read_csv(input_csv, parse_dates=["filingDate"])

    # 2) Clean tickers
    df = df.dropna(subset=["ticker"]).copy()
    df["ticker"] = df["ticker"].astype(str)

    # 3) Compute price-change features
    price_feats = df.apply(
        lambda row: get_price_changes(row["ticker"], row["filingDate"]),
        axis=1, result_type="expand"
    )
    price_feats.columns = ["pct_1d", "pct_3d"]

    # 4) Merge back into main DataFrame
    df["pct_1d"] = price_feats["pct_1d"]
    df["pct_3d"] = price_feats["pct_3d"]
    df["label_1d_extreme"] = df["pct_1d"].apply(
        lambda x: 1 if x is not None and x >= 0.05
                  else (-1 if x is not None and x <= -0.05 else 0)
    )
    df["label_3d_extreme"] = df["pct_3d"].apply(
        lambda x: 1 if x is not None and x >= 0.10
                  else (-1 if x is not None and x <= -0.10 else 0)
    )
    df.drop(columns=["pct_1d", "pct_3d"], inplace=True)

    # 6) Drop filingDate before saving to CSV
    df.drop(columns=["filingDate"], inplace=True)
    df.to_csv(output_csv, index=False)
    print(f"✅ Wrote {len(df)} rows with labels to {output_csv}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Attach 1d and 3d multiclass labels to scraper output"
    )
    p.add_argument(
        "--input", "-i",
        default="flagged_filings.csv",
        help="Path to input CSV from Scraper.py"
    )
    p.add_argument(
        "--output", "-o",
        default="labeled_filings.csv",
        help="Path for output CSV with label_1d_extreme & label_3d_extreme"
    )
    args = p.parse_args()
    main(args.input, args.output)