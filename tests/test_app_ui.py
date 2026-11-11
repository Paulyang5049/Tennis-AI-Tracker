import gradio as gr

from tennis_ai.app import create_app
from tennis_ai.ui import progress_card, status_card


def test_experimental_processing_options_default_to_baselines(tmp_path):
    app = create_app(tmp_path)
    dropdowns = {
        block.label: block for block in app.blocks.values() if isinstance(block, gr.Dropdown)
    }
    assert dropdowns["Ball tracker"].value == "baseline-v1"
    assert dropdowns["Hit candidate detector"].value == "baseline-v1"
    assert ("contact-v2", "contact-v2") in dropdowns["Hit candidate detector"].choices
    assert dropdowns["Stroke type candidates"].value == ""
    assert ("stroke-v1", "stroke-v1") in dropdowns["Stroke type candidates"].choices
    assert dropdowns["Spin candidates"].value == ""


def test_progress_escapes_untrusted_status_and_never_uses_simulated_progress():
    output = status_card("23% · Processing <img src=x onerror=alert(1)>")
    assert 'value="23"' in output
    assert "<img" not in output
    assert "&lt;img" in output
    assert "<progress" not in status_card("")
    assert 'value="100"' in progress_card(4, "Done", "complete")
    assert 'value="0"' in progress_card(float("nan"), "Loading", "running")


def test_terminal_status_is_distinguished_from_success():
    assert "Your replay is ready" in status_card("100% · Complete")
    assert "Progress saved" in status_card("Paused · Analysis paused; use Resume to continue")
    assert "Needs your attention" in status_card("Stopped · Cannot read recording")
    assert "Your replay is ready" not in status_card("Stopped · Cannot read recording")


def test_tactics_tab_offers_both_views_with_assisted_default(tmp_path):
    app = create_app(tmp_path)
    radios = {b.label: b for b in app.blocks.values() if isinstance(b, gr.Radio)}
    assert radios["View"].value == "assisted"
    assert set(radios["View"].choices) == {
        ("assisted", "assisted"),
        ("human_verified", "human_verified"),
    }
    buttons = {b.value for b in app.blocks.values() if isinstance(b, gr.Button)}
    assert {"Show tendency", "Export scouting report"} <= buttons


def test_tactics_handlers_run_on_the_shared_v3_fixture(tmp_path):
    import shutil
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "contracts/fixtures/v3/full"
    folder = tmp_path / "match"
    shutil.copytree(fixture, folder)
    app = create_app(tmp_path)
    handlers = {block.fn.__name__: block.fn for block in app.fns.values() if block.fn}
    players = handlers["tactic_players"](str(folder))
    assert players["value"] in {"self", "opponent"} or players["choices"]
    image, summary, table = handlers["show_tendency"](
        str(folder), "human_verified", "self", "", "any", "any", "any", "any", "any", 8
    )
    assert image.ndim == 3 and "1 shots" in summary and table[0][0] == "shot-1"
    files = handlers["scouting_export"](str(folder), "human_verified", "self", "", 8)
    assert Path(files[0]).read_text().startswith("# Scouting report: self")
    assert (folder / "reports").is_dir()
