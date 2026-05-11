"""Parse Excel and CSV files into raw tabular data."""
import pandas as pd
import json
import os
from typing import List, Dict, Any, Tuple


def parse_file(file_path: str) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """
    Parse an uploaded Excel or CSV file.
    Returns: (rows as list of dicts, column names, row_count)
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, dtype=str)
        elif ext == ".csv":
            # Try UTF-8 first, fall back to Thai encoding
            try:
                df = pd.read_csv(file_path, dtype=str, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, dtype=str, encoding="tis-620")
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        df = df.dropna(how="all")               # drop completely empty rows
        df.columns = [str(c).strip() for c in df.columns]

        rows = df.to_dict(orient="records")
        # Clean NaN / None to None
        clean_rows = []
        for row in rows:
            clean_row = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            clean_rows.append(clean_row)

        return clean_rows, list(df.columns), len(clean_rows)

    except Exception as e:
        raise RuntimeError(f"Failed to parse {file_path}: {e}")


def get_sample_rows(rows: List[Dict], n: int = 5) -> List[Dict]:
    """Return first n non-empty rows for preview."""
    return rows[:n]
