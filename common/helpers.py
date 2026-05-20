def pad_hex(color: str | None, default="333333") -> str:
    """Return a #RRGGBB string (expands 3-digit, handles None)."""
    if not isinstance(color, str) or not color.strip():
        return f"#{default.upper()}"
    c = color.strip().lstrip("#").upper()
    if len(c) == 3 and all(ch in "0123456789ABCDEF" for ch in c):
        c = "".join(ch * 2 for ch in c)
    c = (c + "000000")[:6]  # pad if someone passed short weird strings
    return f"#{c}"
