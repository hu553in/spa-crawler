import logging


def _apply_level(level: int) -> None:
    """Set a logging level for root and already-created named loggers."""
    logging.getLogger().setLevel(level)

    mgr = logging.root.manager
    for logger in mgr.loggerDict.values():
        if isinstance(logger, logging.PlaceHolder):
            continue
        logger.setLevel(level)


def setup_logging(*, verbose: bool, quiet: bool) -> bool:
    """
    Configure logging level from CLI flags and return effective verbose mode.

    Priority:
      - Quiet -> ``CRITICAL`` (suppress runtime logs).
      - Verbose -> ``INFO``.
      - Default -> ``WARNING``.
    """
    if quiet:
        _apply_level(logging.CRITICAL)
        return False

    if verbose:
        _apply_level(logging.INFO)
        return True

    _apply_level(logging.WARNING)
    return False
