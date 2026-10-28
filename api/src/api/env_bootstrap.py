"""Load environment configuration before controllers read it at import time."""

from dotenv import load_dotenv
from storage.global_config import load_global_config

load_dotenv()
load_global_config()
