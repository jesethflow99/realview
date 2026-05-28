import csv
import logging
import shutil
import tempfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".parquet"}


def _detect_delimiter(filepath: str, sample_bytes: int = 8192) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(sample_bytes)
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        pass

    delimiters = [",", ";", "\t", "|"]
    counts = {}
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(5)]
        for d in delimiters:
            counts[d] = sum(len(line.split(d)) for line in lines if line.strip())
        if counts:
            return max(counts, key=counts.get)
    except Exception:
        pass
    return ","


def _detect_encoding(filepath: str) -> str:
    try:
        import chardet
        with open(filepath, "rb") as f:
            raw = f.read(10000)
        result = chardet.detect(raw)
        if result["confidence"] > 0.7:
            return result["encoding"]
    except ImportError:
        pass
    except Exception:
        pass

    for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                f.read(1024)
            return enc
        except (UnicodeDecodeError, Exception):
            continue
    return "utf-8"


def _copy_to_temp(filepath: str) -> str:
    fp = Path(filepath)
    tmp = Path(tempfile.gettempdir()) / f"_realview_read_{fp.name}"
    shutil.copy2(filepath, tmp)
    return str(tmp)


def _read_csv_safe(filepath: str, delimiter: str = None, encoding: str = None, skip_rows: int = 0) -> pd.DataFrame:
    source = filepath
    for attempt in range(3):
        try:
            if delimiter is None:
                delimiter = _detect_delimiter(filepath)
            if encoding is None:
                encoding = _detect_encoding(filepath)
            logger.info(f"Reading CSV: delimiter={repr(delimiter)}, encoding={encoding}")
            return pd.read_csv(
                source, delimiter=delimiter, skiprows=skip_rows,
                encoding=encoding, low_memory=False, on_bad_lines="warn",
            )
        except (PermissionError, OSError):
            if attempt < 2:
                continue
            source = _copy_to_temp(filepath)
        except UnicodeDecodeError as e:
            if attempt < 2:
                encoding = "latin-1"
                continue
            raise
    raise RuntimeError(f"Could not read {filepath} after 3 attempts")


def _read_excel_safe(filepath: str, skip_rows: int = 0, sheet_name=0) -> pd.DataFrame:
    source = filepath
    for attempt in range(3):
        try:
            return pd.read_excel(source, sheet_name=sheet_name, skiprows=skip_rows)
        except (PermissionError, OSError):
            if attempt < 2:
                continue
            source = _copy_to_temp(filepath)
    raise RuntimeError(f"Could not read Excel file {filepath} after 3 attempts")


def extract(filepath: str | Path, **kwargs) -> pd.DataFrame:
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {SUPPORTED_EXTENSIONS}")

    logger.info(f"Extracting data from {path.name}")

    try:
        if ext in (".csv", ".tsv", ".txt"):
            delimiter = kwargs.get("delimiter", None)
            if ext == ".tsv":
                delimiter = delimiter or "\t"
            encoding = kwargs.get("encoding", None)
            return _read_csv_safe(
                filepath, delimiter=delimiter, encoding=encoding,
                skip_rows=kwargs.get("skip_rows", 0),
            )

        elif ext in (".xlsx", ".xls"):
            return _read_excel_safe(
                filepath,
                sheet_name=kwargs.get("sheet_name", 0),
                skip_rows=kwargs.get("skip_rows", 0),
            )

        elif ext == ".json":
            return pd.read_json(
                filepath,
                orient=kwargs.get("json_orient", "records"),
                encoding=kwargs.get("encoding", "utf-8"),
            )

        elif ext == ".parquet":
            return pd.read_parquet(filepath)

        raise ValueError(f"Unsupported file type: {ext}")

    except Exception as e:
        logger.error(f"Failed to extract {path.name}: {e}")
        raise
