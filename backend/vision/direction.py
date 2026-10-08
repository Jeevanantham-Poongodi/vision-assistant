def get_direction(cx_norm: float) -> str:
    """Return the contract direction zone for a normalized horizontal center."""
    cx_norm = min(1.0, max(0.0, cx_norm))
    if cx_norm < 0.2:
        return "left"
    if cx_norm < 0.4:
        return "slight_left"
    if cx_norm <= 0.6:
        return "center"
    if cx_norm <= 0.8:
        return "slight_right"
    return "right"