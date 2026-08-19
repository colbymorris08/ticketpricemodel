"""Shared paths and constants for ticket price model sprint."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIXTURES = DATA / "fixtures"
REFERENCE = DATA / "reference"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
RESULTS = ROOT / "results"

COVENTRY_FIXTURES = FIXTURES / "coventry_2026_27_home.csv"
PORTLAND_FIXTURES = FIXTURES / "portland_fire_2026_home.csv"
PL_SEED = REFERENCE / "pl_promoted_home_seed.csv"
WNBA_OBSERVED = REFERENCE / "wnba_home_prices_observed.csv"
PRIMARY_BANDS = REFERENCE / "primary_bands.csv"

FORECAST_HORIZONS = (30, 14, 3)

# Opponent tier mapping for WNBA (1=weak draw, 5=marquee)
WNBA_TIER = {
    "Las Vegas Aces": 5,
    "New York Liberty": 5,
    "Indiana Fever": 4,
    "Seattle Storm": 4,
    "Minnesota Lynx": 4,
    "Golden State Valkyries": 4,
    "Phoenix Mercury": 3,
    "Chicago Sky": 3,
    "Los Angeles Sparks": 3,
    "Toronto Tempo": 3,
    "Connecticut Sun": 2,
    "Atlanta Dream": 2,
    "Dallas Wings": 2,
    "Washington Mystics": 2,
}

BIG_SIX = {
    "Arsenal", "Chelsea", "Liverpool", "Manchester City",
    "Manchester United", "Tottenham Hotspur",
}
