
import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent

ARTIFACTS_DIR = ROOT_DIR / "artifacts"

DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(ROOT_DIR / "research.db"))
)

APP_NAME = "Reproducible Research Platform"
    
