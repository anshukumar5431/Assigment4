#!/usr/bin/env python3
"""
run.py

This is my batch job script for Task 0. Basic idea: read some OHLCV data,
compute a rolling mean on the close price, turn that into a simple
up/down signal, and log everything + dump the metrics to a json file.

I tried to keep it deterministic (fixed seed) and to make sure it doesn't
just crash silently if something's wrong with the input -- instead it
should log the error and still write out a metrics.json (just with an
error status) so whatever is checking the output always has something
to read.

Run it like this:
    python run.py --input data.csv --config config.yaml \
                   --output metrics.json --log-file run.log

(all 4 args are required, nothing is hard-coded so it should work the
same locally or inside the Docker container)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# these three have to be present in config.yaml or we bail out early
REQUIRED_CONFIG_FIELDS = ("seed", "window", "version")


def parse_args():
    parser = argparse.ArgumentParser(description="Rolling-mean signal batch job.")
    parser.add_argument("--input", required=True, help="Path to input OHLCV CSV file.")
    parser.add_argument("--config", required=True, help="Path to YAML config file.")
    parser.add_argument("--output", required=True, help="Path to write metrics JSON.")
    parser.add_argument("--log-file", required=True, help="Path to write the run log.")
    return parser.parse_args()


def setup_logging(log_file: str) -> logging.Logger:
    # writing to both a file and stdout -- file gets everything (DEBUG+),
    # stdout only gets INFO+ so the console doesn't get too spammy
    logger = logging.getLogger("mlops_task")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # avoids duplicate log lines if this ever gets called twice

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_file, mode="w")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def load_config(config_path: str, logger: logging.Logger) -> dict:
    """Load and sanity-check config.yaml. Raises if anything looks off."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(path, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Config file is not valid YAML: {e}")

    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML mapping (key: value pairs).")

    missing = [field for field in REQUIRED_CONFIG_FIELDS if field not in config]
    if missing:
        raise ValueError(f"Config missing required field(s): {missing}")

    # window needs to be at least 2, otherwise "rolling mean" doesn't really mean anything
    if not isinstance(config["window"], int) or config["window"] < 2:
        raise ValueError("Config field 'window' must be an integer >= 2.")

    if not isinstance(config["seed"], int):
        raise ValueError("Config field 'seed' must be an integer.")

    logger.info(
        "Config loaded and validated: seed=%s, window=%s, version=%s",
        config["seed"], config["window"], config["version"],
    )
    return config


def load_dataset(input_path: str, logger: logging.Logger) -> pd.DataFrame:
    """Read the input CSV and make sure it's actually usable before we touch it."""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if path.stat().st_size == 0:
        raise ValueError(f"Input file is empty: {input_path}")

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        raise ValueError(f"Input file is empty or has no parsable columns: {input_path}")
    except pd.errors.ParserError as e:
        raise ValueError(f"Input file is not valid CSV: {e}")

    if df.empty:
        raise ValueError(f"Input file has no data rows: {input_path}")

    if "close" not in df.columns:
        raise ValueError("Input CSV is missing required column: 'close'")

    # just in case close got read in as strings/objects, try to coerce it
    if not pd.api.types.is_numeric_dtype(df["close"]):
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        if df["close"].isna().all():
            raise ValueError("Column 'close' contains no valid numeric data.")

    logger.info("Dataset loaded: %d rows from %s", len(df), input_path)
    return df


def compute_signal(df: pd.DataFrame, window: int, logger: logging.Logger) -> pd.DataFrame:
    """
    Computes rolling mean of close + a binary signal (1 if close is above
    its own rolling mean, 0 otherwise).

    Note: the first (window - 1) rows won't have enough history to compute
    a full rolling mean, so pandas gives NaN there (I set min_periods=window
    on purpose so it doesn't fill those in with a partial average). Those
    rows still count toward rows_processed, they just don't count toward
    signal_rate since there's no real signal for them.
    """
    df = df.copy()
    df["rolling_mean"] = df["close"].rolling(window=window, min_periods=window).mean()
    logger.info("Rolling mean computed on 'close' with window=%d", window)

    df["signal"] = np.where(
        df["rolling_mean"].isna(), np.nan, (df["close"] > df["rolling_mean"]).astype(float)
    )
    logger.info(
        "Signal generated: %d rows with valid signal (first %d rows excluded due to warm-up window)",
        int(df["signal"].notna().sum()), window - 1,
    )
    return df


def main():
    args = parse_args()
    logger = setup_logging(args.log_file)
    start_time = time.perf_counter()
    logger.info("Job started")

    config = {"version": "v1"}  # fallback so error payload still has a version if config load fails

    try:
        config = load_config(args.config, logger)
        np.random.seed(config["seed"])
        logger.info("Random seed set to %d for reproducibility", config["seed"])

        df = load_dataset(args.input, logger)
        df = compute_signal(df, config["window"], logger)

        rows_processed = len(df)
        signal_rate = float(df["signal"].dropna().mean())
        latency_ms = int(round((time.perf_counter() - start_time) * 1000))

        metrics = {
            "version": config["version"],
            "rows_processed": rows_processed,
            "metric": "signal_rate",
            "value": round(signal_rate, 4),
            "latency_ms": latency_ms,
            "seed": config["seed"],
            "status": "success",
        }

        logger.info(
            "Metrics summary: rows_processed=%d, signal_rate=%.4f, latency_ms=%d",
            rows_processed, signal_rate, latency_ms,
        )

        with open(args.output, "w") as f:
            json.dump(metrics, f, indent=2)

        logger.info("Job ended: status=success")
        print(json.dumps(metrics, indent=2))
        sys.exit(0)

    except Exception as e:
        # catch-all so we always write a metrics.json even on failure --
        # figured whatever grades/checks this shouldn't have to go dig
        # through the log file just to see that it failed
        error_metrics = {
            "version": config.get("version", "v1"),
            "status": "error",
            "error_message": str(e),
        }
        logger.error("Validation/processing error: %s", e, exc_info=True)

        with open(args.output, "w") as f:
            json.dump(error_metrics, f, indent=2)

        logger.info("Job ended: status=error")
        print(json.dumps(error_metrics, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
