#!/usr/bin/env python3
"""
Scraper.py
----------
Fetches the SEC EDGAR daily master index, filters for user-defined forms and keywords,
downloads matching filings, and outputs flagged entries to CSV for downstream analysis.

Usage:
    python Scraper.py [YYYYMMDD] [output.csv]

If no date is provided, defaults to yesterday's date.
"""


import requests
import pandas as pd
import time
from datetime import datetime, timedelta
import sys
import os
import contextlib
import io
import openai
from openai import OpenAI
from tqdm import tqdm
import yfinance as yf
import re
from datetime import timedelta
import openpyxl
import json


# -- OpenAI Configuration --
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))  # Make sure to set this env var

# -- Configuration --
# IMPORTANT: Replace <your_email@domain.com> with your contact email per SEC guidelines.
USER_AGENT = "MyScraperApp/1.0 (your_email@domain.com)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.sec.gov",
    "Connection": "keep-alive"
}

# Forms and keywords to flag
FORM_TYPES = ["8-K", "4", "13D", "13G", "DEF 14A"]
KEYWORDS = [
    "private placement",
    "securities purchase agreement",
    "entered into agreement",
    "filed a shelf registration",
    "acquired beneficial ownership",
    "reverse stock split",
    "PIPE financing",
    "at-the-market-offering",
    "public offering",
    "debt financing"
    # add more patterns here as needed
]

def get_cik_ticker_map():
    """
    Fetch the SEC's ticker-to-CIK JSON.
    Returns two dicts:
      - ticker_to_cik: {TICKER: CIK}
      - cik_to_ticker: {CIK: TICKER}
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    ticker_to_cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}
    cik_to_ticker = {cik: ticker for ticker, cik in ticker_to_cik.items()}
    return ticker_to_cik, cik_to_ticker

def fetch_master_index(date):
    """
    Download the EDGAR master index for the given date (YYYYMMDD).
    Returns the raw text of the index.
    """
    dt = datetime.strptime(date, "%Y%m%d")
    year = dt.year
    qtr = (dt.month - 1) // 3 + 1
    idx_url = f"https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{qtr}/master.{date}.idx"
    resp = requests.get(idx_url, headers=HEADERS)
    resp.raise_for_status()
    return resp.text

def parse_index(index_text):
    """
    Parse the master index text and return a list of dicts for entries
    matching FORM_TYPES.
    """
    lines = index_text.splitlines()
    # Find the header line that starts with "CIK|Company Name|Form Type"
    start = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("CIK|Company Name|Form Type"):
            start = idx + 1
            break
    if start is None:
        return []
    entries = []
    for line in lines[start:]:
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik, comp, form, date_str, filename = parts
        if form not in FORM_TYPES:
            continue
        # Parse filing date, handling both 'YYYY-MM-DD' and 'YYYYMMDD'
        if "-" in date_str:
            filing_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            filing_date = datetime.strptime(date_str, "%Y%m%d").date()

        entries.append({
            "cik": cik.zfill(10),
            "form": form,
            "filingDate": filing_date,
            "filename": filename
        })
    return entries

def fetch_document_text(url):
    """Download the filing text/HTML from the given URL."""
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.text

def find_keywords(text, keywords):
    """Return a list of keywords that appear in text (case-insensitive)."""
    tl = text.lower()
    return [kw for kw in keywords if kw in tl]

def summarize_text(text, max_tokens=200):
    """
    Use OpenAI to generate a concise 2–3 sentence summary of key facts and catalysts.
    """
    prompt = (
        "You are a financial research assistant. "
        "Provide a concise 2–3 sentence summary of this SEC filing, "
        "focusing on key facts and catalysts behind the filing. Do NOT include your own interpretation "
        f"Text: {text[:4000]}"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""

# --- Inserted get_price_changes ---
def get_price_changes(ticker, filing_date):
    """
    Returns a Series with price features: pct_1d, pct_3d, pct_before,
    volatility_before, volume_change around filing_date.
    """
    start = filing_date - timedelta(days=7)
    end   = filing_date + timedelta(days=5)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        hist = yf.download(ticker, start=start, end=end, progress=False)

    dates = [d.date() for d in hist.index]
    if filing_date not in dates:
        return pd.Series([None] * 5,
            index=["pct_1d","pct_3d","pct_before","volatility_before","volume_change"]
        )

    idx = dates.index(filing_date)
    close_prev = hist["Close"].iloc[idx-1] if idx-1 >= 0 else None
    close_0    = hist["Close"].iloc[idx]
    close_1d   = hist["Close"].iloc[idx+1] if idx+1 < len(hist) else None
    close_3d   = hist["Close"].iloc[idx+3] if idx+3 < len(hist) else None

    # 1-day return t-1 -> t+1
    pct_1d = (close_1d - close_prev) / close_prev if close_prev and close_1d else None
    pct_3d = (close_3d - close_0)    / close_0    if close_3d else None
    pct_before = (close_0 - close_prev) / close_prev if close_prev else None

    vol_before = hist["Close"].iloc[max(0, idx-5):idx].std()
    try:
        avg_vol_prior = hist["Volume"].iloc[max(0, idx-5):idx].mean()
        volume_change = hist["Volume"].iloc[idx] / avg_vol_prior if avg_vol_prior and not pd.isna(avg_vol_prior) else None
    except:
        volume_change = None

    return pd.Series(
        [pct_1d, pct_3d, pct_before, vol_before, volume_change],
        index=["pct_1d","pct_3d","pct_before","volatility_before","volume_change"]
    )

def main(date_source=None, output_csv="master_flagged_filings.csv"):
    """
    Process either a single date (YYYYMMDD) or a CSV/XLSX file listing dates in a column 'date'.
    Outputs all matching filings across all dates to output_csv.
    """
    if date_source is None:
        df_dates = pd.read_csv("selected_dates.csv")
        date_list = pd.to_datetime(df_dates["date"]).dt.strftime("%Y%m%d").tolist()
    else:
        date_list = [date_source]

    all_results = []
    for date_str in tqdm(date_list, desc="Processing Dates", colour="green"):
        try:
            index_text = fetch_master_index(date_str)
        except requests.exceptions.HTTPError as e:
            print(f"Error fetching index for {date_str}: {e}")
            continue

        entries = parse_index(index_text)
        print(f"Found {len(entries)} filings matching forms {FORM_TYPES} on {date_str}.")
        _, cik_to_ticker = get_cik_ticker_map()

        for entry in tqdm(entries, desc=f"Processing filings on {date_str}", leave=False, colour="cyan"):
            url = f"https://www.sec.gov/Archives/{entry['filename']}"
            try:
                text = fetch_document_text(url)
                matched = find_keywords(text, KEYWORDS)
                if matched:
                    ticker = cik_to_ticker.get(entry["cik"], "")

                    # Compute price features
                    price_feats = get_price_changes(ticker, entry["filingDate"])
                    vol_before    = price_feats["volatility_before"]
                    volume_change = price_feats["volume_change"]

                    # Text-based features
                    summary_text = summarize_text(text)

                    # Fundamental features
                    info = yf.Ticker(ticker).info
                    market_cap = info.get("marketCap", None)
                    sector     = info.get("sector",   None)

                    all_results.append({
                        "ticker": ticker,
                        "form": entry["form"],
                        "filingDate": entry["filingDate"],
                        "keywords": ";".join(matched),
                        "summary": summary_text,
                        "volatility_before": vol_before,
                        "summary_length": len(summary_text),
                        "has_numbers": bool(re.search(r"\d", summary_text)),
                        "num_keywords_matched": len(matched),
                        "market_cap": market_cap,
                        "sector": sector
                    })
                time.sleep(0.2)
            except Exception as e:
                continue

    df = pd.DataFrame(all_results)
    df = df[[
        "ticker",
        "form",
        "filingDate",
        "keywords",
        "summary",
        "volatility_before",
        "summary_length",
        "has_numbers",
        "num_keywords_matched",
        "market_cap",
        "sector"
    ]]
    if os.path.exists(output_csv):
        existing_df = pd.read_csv(output_csv)
        df = pd.concat([existing_df, df], ignore_index=True).drop_duplicates()
    df.to_csv(output_csv, index=False)
    print(f"Saved {len(df)} flagged filings to {output_csv}")

if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "master_flagged_filings.csv"
    main(date_arg, out_arg)
