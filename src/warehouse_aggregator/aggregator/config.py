import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

DB_DSN: str = os.environ["DB_DSN"]

# Battery drainage rate used for energy-budget calculations.
BATTERY_PCT_PER_METER = 0.2
