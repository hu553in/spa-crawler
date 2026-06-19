import logging

from spa_crawler.logging import setup_logging


def test_setup_logging_sets_levels_and_effective_verbose() -> None:
    named = logging.getLogger("spa-crawler-test")
    root = logging.getLogger()
    root.setLevel(logging.ERROR)
    named.setLevel(logging.ERROR)

    assert setup_logging(verbose=False, quiet=False) is False
    assert root.level == logging.WARNING
    assert named.level == logging.WARNING

    assert setup_logging(verbose=True, quiet=False) is True
    assert root.level == logging.INFO
    assert named.level == logging.INFO

    assert setup_logging(verbose=True, quiet=True) is False
    assert root.level == logging.CRITICAL
    assert named.level == logging.CRITICAL
