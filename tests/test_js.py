from spa_crawler import js_scripts


def test_load_js_and_cache() -> None:
    js_scripts.load_js.cache_clear()
    content1 = js_scripts.load_js("dismiss_overlays.js")
    content2 = js_scripts.load_js("dismiss_overlays.js")
    assert content1
    assert content1 == content2
    assert js_scripts.load_js.cache_info().hits >= 1
