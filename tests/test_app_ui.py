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
