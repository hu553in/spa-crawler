import typer
from yarl import URL

from spa_crawler import __main__ as main_mod


def test_main_builds_config_and_calls_crawl(monkeypatch, capsys) -> None:
    captured = {}

    async def fake_crawl(cfg) -> None:
        captured["config"] = cfg

    monkeypatch.setattr(main_mod, "crawl", fake_crawl)
    main_mod.main(
        base_url="https://example.com",
        login_required=False,
        quiet=False,
        include_links_regex=["^https://example.com/.*"],
    )

    cfg = captured["config"]
    assert cfg.base_url == URL("https://example.com")
    assert cfg.login_required is False
    assert cfg.api_path_prefixes == ["/api"]
    out = capsys.readouterr().out
    assert "base_url" in out


def test_main_quiet_does_not_print(monkeypatch, capsys) -> None:
    async def fake_crawl(_cfg) -> None:
        return None

    monkeypatch.setattr(main_mod, "crawl", fake_crawl)
    main_mod.main(base_url="https://example.com", login_required=False, quiet=True)
    assert capsys.readouterr().out == ""


def test_main_param_error_passthrough() -> None:
    err = typer.BadParameter("x")
    assert main_mod.is_cli_param_error(err)
    assert not main_mod.is_cli_param_error(RuntimeError("x"))
