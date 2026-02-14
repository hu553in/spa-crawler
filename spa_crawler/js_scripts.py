from functools import lru_cache
from pathlib import Path

_JS_DIR = Path(__file__).resolve().parent / "js"


@lru_cache(maxsize=32)
def load_js(filename: str) -> str:
    """Load a JS snippet from spa_crawler/js/<filename> (cached)."""
    return (_JS_DIR / filename).read_text(encoding="utf-8")
