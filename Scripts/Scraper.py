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
import openai
from openai import OpenAI
from tqdm import tqdm

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
FORM_TYPES = ["8-K", "4", "13D", "13G", "S-3", "S-1", "DEF 14A"]
KEYWORDS = [
    "private placement",
    "securities purchase agreement",
    "entered into agreement",
    "filed a shelf registration",
    "acquired beneficial ownership",
    "reverse stock split",
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
    Use OpenAI to generate a concise summary of the filing text.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "You are a financial research assistant."},
                {"role": "user", "content": (
                    "Please summarize the following SEC filing in 2-3 sentences, "
                    "focusing on the key catalyst. Leave out your own interpretation, "
                    "rather focusing on just presenting the key facts: \n\n" + text[:4000]
                )}
            ],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI summarization error: {e}")
        return ""

def main(date_source=None, output_csv="flagged_filings.csv"):
    """
    Process either a single date (YYYYMMDD) or a CSV/XLSX file listing dates in a column 'date'.
    Outputs all matching filings across all dates to output_csv.
    """
    # If no date_source provided, but a default date file exists, use it
    default_file = os.path.join(os.path.dirname(__file__), "selected_dates.xlsx")
    if date_source is None and os.path.isfile(default_file):
        date_source = default_file
    # Load date list
    date_list = []
    if date_source and os.path.isfile(date_source):
        # Read CSV or Excel file
        if date_source.lower().endswith((".csv", ".txt")):
            df_dates = pd.read_csv(date_source, parse_dates=["date"])
        else:
            df_dates = pd.read_excel(date_source, parse_dates=["date"])
        # Format dates as YYYYMMDD strings
        date_list = df_dates["date"].dt.strftime("%Y%m%d").tolist()
    elif date_source:
        date_list = [date_source]
    else:
        # Fallback to last available master index within past 7 days
        for d in range(1, 8):
            candidate = (datetime.now() - timedelta(days=d)).strftime("%Y%m%d")
            try:
                fetch_master_index(candidate)
                date_list = [candidate]
                print(f"Using master index for {candidate}")
                break
            except requests.exceptions.HTTPError:
                continue
        if not date_list:
            print("Error: Could not fetch a master index in the past 7 days.")
            sys.exit(1)

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
                    summary = summarize_text(text)
                    all_results.append({
                        "ticker": ticker,
                        "cik": entry["cik"],
                        "form": entry["form"],
                        "filingDate": entry["filingDate"],
                        "url": url,
                        "keywords": ";".join(matched),
                        "summary": summary
                    })
                time.sleep(0.2)
            except Exception as e:
                print(f"Error fetching {url}: {e}")

    df = pd.DataFrame(all_results)
    df.to_csv(output_csv, index=False)
    print(f"Saved {len(df)} flagged filings to {output_csv}")

if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "flagged_filings.csv"
    main(date_arg, out_arg)
