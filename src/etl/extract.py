import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def extract(filepath: str | Path, **kwargs) -> pd.DataFrame:
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {SUPPORTED_EXTENSIONS}")

    logger.info(f"Extracting data from {path.name}")

    try:
        if ext == ".csv":
            df = pd.read_csv(
                path,
                delimiter=kwargs.get("delimiter", ","),
                skiprows=kwargs.get("skip_rows", 0),
                encoding=kwargs.get("encoding", "utf-8"),
                low_memory=False,
            )
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(
                path,
                sheet_name=kwargs.get("sheet_name", 0),
                skiprows=kwargs.get("skip_rows", 0),
            )
        elif ext == ".json":
            df = pd.read_json(path, orient=kwargs.get("json_orient", "records"))
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        logger.info(f"Extracted {len(df)} rows from {path.name}")
        return df

    except Exception as e:
        logger.error(f"Failed to extract {path.name}: {e}")
        raise
