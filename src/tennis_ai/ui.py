"""Local-only visual theme and accessible, evidence-based progress presentation."""

import math
import re
from html import escape

import gradio as gr

HERO = """<header class="tennis-hero">
<div class="hero-copy"><div class="eyebrow"><span class="brand-ball" aria-hidden="true"></span>TENNIS AI <span class="local-badge">ON YOUR COMPUTER</span></div>
<h1>Every rally,<br><em>worth revisiting.</em></h1>
<p>Your recordings. A closer look at your game.<br>Import, review and keep the moments that matter.</p>
<div class="hero-tags"><span>Singles &amp; doubles</span><span>Private by design</span></div></div>
<div class="court-art" aria-hidden="true"><svg viewBox="0 0 420 300"><g fill="none" stroke="#92AF8B" stroke-width="2"><path d="M60 35h300v230H60zM93 35v230m234-230v230M60 150h300M93 85h234m-234 130h234M210 85v130"/><path d="M48 150h324" stroke-width="5"/></g><path d="M140 255Q95 165 250 85" fill="none" stroke="#D5E84C" stroke-width="3" stroke-dasharray="5 9"/><circle cx="264" cy="72" r="31" fill="#D5E84C"/><path d="M247 47q38 26 3 51m31-51q-31 28 10 38" fill="none" stroke="#F6F5ED" stroke-width="2.5"/></svg><span>A fresh perspective on your court.</span></div></header>"""


def progress_card(fraction=0.0, message="Choose a recording or open a saved match.", phase="idle"):
    """Only actual pipeline callbacks advance this bar; idle is never simulated work."""
    if phase not in {"idle", "running", "complete", "paused", "failed"}:
        phase = "idle"
    value = float(fraction)
    value = min(1.0, max(0.0, value)) if math.isfinite(value) else 0.0
    titles = {
        "idle": "Ready when you are",
        "running": "Working on your match",
        "complete": "Your replay is ready",
        "paused": "Progress saved",
        "failed": "Needs your attention",
    }
    percent = round(value * 100)
    meter = (
        f'<progress max="100" value="{percent}" aria-label="Analysis progress">{percent}%</progress>'
        if phase != "idle"
        else ""
    )
    badge = (
        f"{percent}%"
        if phase == "running"
        else {"idle": "LOCAL", "complete": "COMPLETE", "paused": "PAUSED", "failed": "STOPPED"}[
            phase
        ]
    )
    return f'<div class="activity-card {phase}" role="status" aria-live="polite"><div class="activity-title"><strong>{titles[phase]}</strong><span>{badge}</span></div><p>{escape(str(message))}</p>{meter}</div>'


def status_card(message):
    text = str(message or "")
    match = re.match(r"^(\d+)%\s*·\s*(.*)", text)
    if match:
        fraction = int(match[1]) / 100
        return progress_card(fraction, match[2], "complete" if fraction >= 1 else "running")
    if text.lower() in {"complete", "inference_complete"}:
        return progress_card(1, "Open Video review to explore this saved match.", "complete")
    if text.startswith("Paused") or text.lower() in {"paused", "cancelled"}:
        return progress_card(0, text, "paused")
    if text.startswith("Stopped") or text.lower() == "failed":
        return progress_card(0, text, "failed")
    if text.startswith(("Starting", "Cancellation")):
        return progress_card(0, text, "running")
    return progress_card(0, text or "Choose a recording or open a saved match.")


def theme():
    return gr.themes.Soft(
        primary_hue="lime",
        secondary_hue="emerald",
        neutral_hue="stone",
        font=["-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
    ).set(
        checkbox_label_background_fill_selected="#D5E84C",
        checkbox_label_background_fill_selected_dark="#D5E84C",
        checkbox_label_text_color_selected="#173F35",
        checkbox_label_text_color_selected_dark="#173F35",
        checkbox_background_color_selected="#173F35",
        checkbox_background_color_selected_dark="#173F35",
        slider_color="#557731",
        slider_color_dark="#D5E84C",
        body_background_fill="#F6F5ED",
        body_background_fill_dark="#102D26",
        body_text_color="#173F35",
        body_text_color_dark="#F6F5ED",
        block_background_fill="#FFFFFF",
        block_background_fill_dark="#1C4036",
        block_border_color="#DCE2D6",
        block_border_color_dark="#3B5C50",
        block_label_background_fill="#FFFFFF",
        block_label_background_fill_dark="#1C4036",
        block_label_text_color="#3D594C",
        block_label_text_color_dark="#D9E3D5",
        block_title_text_color="#173F35",
        block_title_text_color_dark="#F6F5ED",
        input_background_fill="#F9FAF5",
        input_background_fill_dark="#173F35",
        input_border_color="#CBD5C6",
        input_border_color_dark="#547360",
        input_placeholder_color="#667564",
        input_placeholder_color_dark="#B2C6B6",
        button_primary_background_fill="#D5E84C",
        button_primary_background_fill_hover="#E0EF79",
        button_primary_background_fill_dark="#D5E84C",
        button_primary_background_fill_hover_dark="#E0EF79",
        button_primary_text_color="#173F35",
        button_primary_text_color_hover="#173F35",
        button_primary_text_color_dark="#173F35",
        button_primary_text_color_hover_dark="#173F35",
        button_secondary_background_fill="#EDF0E5",
        button_secondary_background_fill_hover="#E0E7D6",
        button_secondary_background_fill_dark="#315648",
        button_secondary_background_fill_hover_dark="#416957",
        button_secondary_text_color="#173F35",
        button_secondary_text_color_dark="#F6F5ED",
        border_color_primary="#DCE2D6",
        border_color_primary_dark="#3B5C50",
        color_accent_soft="#EDF2D5",
        color_accent_soft_dark="#315648",
    )


CSS = """
:root { color-scheme: light; }
body { background: #F6F5ED; }
.gradio-container { width:100%!important; min-width:0!important; max-width:1280px!important; margin:auto!important; padding:clamp(12px,2vw,28px)!important; }
footer { display:none!important; }
.gradio-container .main.fillable { padding:0!important; width:100%!important; min-width:0!important; }
.gradio-container .contain { min-width:0!important; width:100%!important; }
.tennis-hero { display:flex; align-items:center; justify-content:space-between; gap:30px; padding:34px 42px 30px; border-radius:26px; background:#173F35; color:#F6F5ED; margin-bottom:18px; overflow:hidden; }
.hero-copy { flex:1; min-width:0; }
.eyebrow { display:flex; align-items:center; gap:10px; font-size:13px; font-weight:750; letter-spacing:2px; color:#F6F5ED!important; }
.brand-ball { width:17px; height:17px; border-radius:50%; background:#D5E84C; display:inline-block; }
.local-badge { margin-left:10px; font-size:9px; letter-spacing:1.3px; padding:6px 9px; border:1px solid #74917C; border-radius:20px; color:#DBE9CD; }
.tennis-hero h1 { font-size:clamp(32px,4vw,51px)!important; line-height:1.09!important; letter-spacing:-1.6px; margin:24px 0 14px!important; color:#F6F5ED!important; font-weight:700; }
.tennis-hero h1 em { font-style:normal; color:#D5E84C; }
.tennis-hero p { font-size:14px; line-height:1.65; color:#D7E2D5; margin:0; }
.hero-tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:20px; }
.hero-tags span { font-size:11px; color:#E0EAD8; padding:5px 10px; border-radius:14px; background:#2A5143; }
.court-art { width:37%; max-width:370px; color:#92AF8B; transform:rotate(-7deg); text-align:center; }
.court-art svg { width:100%; display:block; }
.court-art span { font-size:11px; letter-spacing:.5px; color:#BED0B6; }
#workspace-tabs .tab-wrapper { min-width:0; height:auto!important; }
#workspace-tabs [role="tablist"] { height:auto!important; min-height:54px; border:0; gap:7px; padding:7px; background:#E9EDE0; border-radius:16px; margin-bottom:20px; display:flex; flex-wrap:wrap; }
#workspace-tabs [role="tablist"] button { height:auto!important; min-height:40px; border:0!important; border-radius:11px!important; padding:12px 16px!important; color:#486044; font-weight:650; flex:1; white-space:normal; transition:background 180ms ease,color 180ms ease; }
#workspace-tabs [role="tablist"] button.selected { background:#173F35!important; color:#F6F5ED!important; box-shadow:0 2px 5px #173F3515; }
#workspace-tabs > .tabitem { border:0!important; padding:0!important; background:transparent!important; }
.section-intro { padding:2px 0 10px; }
.section-intro h2 { font-size:25px!important; letter-spacing:-.7px; margin-bottom:7px!important; }
.section-intro p { color:#53684E; font-size:14px; }
.card { border:1px solid #DCE2D6!important; border-radius:20px!important; padding:22px!important; background:white; }
.gradio-container button { transition:background 180ms ease,box-shadow 180ms ease,transform 180ms ease; }
.gradio-container button:not([disabled]):active { transform:translateY(1px); }
.gradio-container button:focus-visible, .gradio-container input:focus-visible, .gradio-container textarea:focus-visible { outline:3px solid #76962D!important; outline-offset:3px; }
.gradio-container button.primary { border:0!important; box-shadow:0 3px 0 #ABB938; font-weight:750; }
#analyze-button { min-height:49px; font-size:15px; }
#upload-video { min-height:220px; border:1px dashed #95AD77; background:#F9FAF3; }
#original-video, #annotated-video { border-radius:18px; overflow:hidden; }
#original-video video, #annotated-video video { background:#102D26; }
.activity-card { padding:17px 22px; border:1px solid #D8DFCE; border-radius:16px; background:#F0F3E7; margin:10px 0 20px; }
.activity-title { display:flex; justify-content:space-between; gap:15px; align-items:center; }
.activity-title strong { font-size:14px; color:#173F35; }
.activity-title span { font-size:10px; letter-spacing:1px; font-weight:700; color:#38532D; background:#DFE8CC; border-radius:20px; padding:5px 9px; }
.activity-card p { margin:6px 0 0; font-size:12px; color:#526649; overflow-wrap:anywhere; }
.activity-card progress { appearance:none; display:block; width:100%; height:5px; border:0; border-radius:8px; overflow:hidden; margin-top:14px; background:#DCE4D0; }
.activity-card progress::-webkit-progress-bar { background:#DCE4D0; }
.activity-card progress::-webkit-progress-value { background:#70902D; border-radius:8px; transition:width 220ms ease; }
.activity-card progress::-moz-progress-bar { background:#70902D; }
.activity-card.complete { border-color:#A7BD87; }
.activity-card.failed { border-color:#B78669; }
.activity-card.failed .activity-title span { background:#F3DACE; color:#7B3927; }
.activity-card.paused .activity-title span { background:#ECE4C4; color:#66501C; }
.gradio-container .form, .gradio-container .block { min-width:0; }
.gradio-container .prose { overflow-wrap:anywhere; }
.gradio-container .label-wrap { transition:background 180ms ease; }
.gradio-container .label-wrap:hover { background:#EDF2E2; }
.dark { color-scheme:dark; }
.dark .section-intro p { color:#C2D3BA; }
.dark #workspace-tabs [role="tablist"] { background:#22463A; }
.dark #workspace-tabs [role="tablist"] button { color:#D5E5CA; }
.dark #workspace-tabs [role="tablist"] button.selected { background:#D5E84C!important; color:#173F35!important; }
.dark .card { background:#1C4036; border-color:#3B5C50!important; }
.dark #upload-video { background:#1C4036; }
.dark .activity-card { background:#24483A; border-color:#547360; }
.dark .activity-title strong { color:#F6F5ED; }
.dark .activity-card p { color:#D5E3CC; }
.dark .gradio-container .label-wrap:hover { background:#315648; }
@media(max-width:700px) {

 .tennis-hero { padding:25px 24px; border-radius:21px; }
 .court-art { display:none; }
 .tennis-hero h1 { font-size:37px!important; }
 .local-badge { font-size:8px; margin-left:0; }
 .eyebrow { gap:7px; font-size:12px; }
 #workspace-tabs [role="tablist"] button { flex:1 1 40%; padding:10px 7px!important; font-size:12px!important; }
 .card { padding:16px!important; }
 .activity-card { padding:15px 16px; }
}
@media(prefers-reduced-motion:reduce) {
 *, *::before, *::after { animation:none!important; transition:none!important; scroll-behavior:auto!important; }
}
"""
