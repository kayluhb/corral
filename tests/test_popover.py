import asyncio

from corral import popover
from corral.state import DONE, IDLE, WAITING, Session

URL = "http://127.0.0.1:5555/focus"


def mk(iterm_id, st, cwd, prompt=""):
    return Session(iterm_id, "c", cwd, st, 1.0, prompt)


def test_render_lists_sessions_with_links_in_order():
    ss = [mk("A-1", WAITING, "/p/hydrogen", "fix it"), mk("B-2", DONE, "/p/lasso")]
    html = popover.render(ss, {"A-1": 1, "B-2": 3}, "B-2", URL, "tok")
    assert html.index("hydrogen") < html.index("lasso")
    assert f"{URL}/A-1?t=tok" in html and f"{URL}/B-2?t=tok" in html
    assert "✋" in html and "fix it" in html
    assert 'class="row current"' in html


def test_render_draws_dots_in_iterm_colours_but_keeps_the_hand():
    html = popover.render([mk("A-1", DONE, "/p/a"), mk("B-2", WAITING, "/p/b")], {}, None, URL, "t")
    assert 'class="dot done"' in html and "🟢" not in html
    assert "✋" in html


def test_render_escapes_project_and_prompt():
    html = popover.render([mk("A-1", WAITING, "/p/<b>", "<script>x</script>")], {}, None, URL, "t")
    assert "<script>x" not in html and "&lt;script&gt;" in html and "&lt;b&gt;" in html


def test_render_when_empty():
    assert "all quiet" in popover.render([], {}, None, URL, "t")


def test_parse_request_needs_token_and_valid_id():
    assert popover.parse_request("GET /focus/A-1?t=tok HTTP/1.1", "tok") == "A-1"
    assert popover.parse_request("GET /focus/A-1?t=bad HTTP/1.1", "tok") is None
    assert popover.parse_request("GET /focus/A-1 HTTP/1.1", "tok") is None
    assert popover.parse_request("GET /focus/../x?t=tok HTTP/1.1", "tok") is None
    assert popover.parse_request("POST /focus/A-1?t=tok HTTP/1.1", "tok") is None
    assert popover.parse_request("garbage", "tok") is None


def test_server_calls_focus_for_valid_requests_only():
    focused = []

    async def scenario():
        async def on_focus(iterm_id):
            focused.append(iterm_id)

        server = await popover.serve(on_focus)
        for path in (f"/focus/A-1?t={server.token}", "/focus/B-2?t=wrong"):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            await writer.drain()
            status = await reader.readline()
            writer.close()
            assert status.startswith(b"HTTP/1.1 ")
        server.close()

    asyncio.run(scenario())
    assert focused == ["A-1"]


def test_render_grouped_puts_rows_under_project_headers():
    ss = [
        mk("A-1", WAITING, "/p/hydrogen", "fix"),
        mk("B-2", DONE, "/p/lasso"),
        mk("C-3", IDLE, "/p/hydrogen", "tests"),
    ]
    html = popover.render(ss, {}, None, URL, "tok", group=True)
    assert html.count('class="group"') == 2
    assert html.index("hydrogen") < html.index("fix") < html.index("tests") < html.index("lasso")


def test_server_closes_idle_connections_quietly(monkeypatch, capsys):
    monkeypatch.setattr(popover, "READ_TIMEOUT", 0.05)

    async def scenario():
        async def on_focus(iterm_id):
            raise AssertionError("no request was sent")

        server = await popover.serve(on_focus)
        # WebKit opens spare connections ahead of time and may never send on them.
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        assert await reader.read() == b""  # the server hung up
        writer.close()
        server.close()

    asyncio.run(scenario())
    assert capsys.readouterr().out == ""


def test_render_shows_the_branch(tmp_path):
    repo = tmp_path / "hydrogen"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/<fix>\n")
    for group in (False, True):
        html = popover.render([mk("A-1", DONE, str(repo))], {}, None, URL, "t", group)
        assert '<span class="branch">&lt;fix&gt;</span>' in html
