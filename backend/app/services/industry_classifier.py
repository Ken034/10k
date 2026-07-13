from typing import Optional


def classify_sector(sic: Optional[str]) -> str:
    if not sic:
        return "regular"
    try:
        code = int(sic)
    except (ValueError, TypeError):
        return "regular"

    if 6000 <= code <= 6199:
        return "banking"
    if 6300 <= code <= 6411:
        return "insurance"
    return "regular"
