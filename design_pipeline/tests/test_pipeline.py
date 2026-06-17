import os, pytest
from PIL import Image
from design_pipeline.main import get_engine, GeminiDesignEngine, MockDesignEngine, extract_element_coordinates, slice_image, typography_engine, optimize_layout_loop, run_pipeline

@pytest.fixture
def sample_input_image(): return Image.open("design_pipeline/mock_assets/sample_input.png")

@pytest.fixture
def master_composition_image(): return Image.open("design_pipeline/mock_assets/master_composition.png")

def test_engine_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(get_engine(), MockDesignEngine)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")
    assert isinstance(get_engine(), GeminiDesignEngine)

def test_extract_element_coordinates(sample_input_image, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    coords = extract_element_coordinates(sample_input_image)
    assert coords["icon"] == [475, 509, 1023, 1537]
    assert coords["text"] == [1023, 509, 1572, 1537]

def test_slice_image(sample_input_image):
    layers = slice_image(sample_input_image, {"icon": [475, 509, 1023, 1537], "text": [1023, 509, 1572, 1537]})
    assert layers["icon"].size == (1028, 548)
    assert layers["text"].size == (1028, 549)

def test_optimize_layout_loop(sample_input_image, master_composition_image, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    coords = extract_element_coordinates(sample_input_image)
    layers = slice_image(sample_input_image, coords)

    # User's icon scaling logic MUST be applied dynamically so it passes with the new image!
    icon = layers["icon"]
    max_icon_width = master_composition_image.width * 0.8
    max_icon_height = master_composition_image.height * 0.6
    if icon.width > max_icon_width or icon.height > max_icon_height:
        scale = min(max_icon_width / icon.width, max_icon_height / icon.height)
        new_width = int(icon.width * scale)
        new_height = int(icon.height * scale)
        icon = icon.resize((new_width, new_height), Image.Resampling.LANCZOS)

    canvas, score, params = optimize_layout_loop(icon, "NEXUS", "DejaVuSans", master_composition_image)
    assert score >= 90.0

def test_run_pipeline(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    output_path = "design_pipeline/mock_assets/output_test.png"
    result = run_pipeline("design_pipeline/mock_assets/config.json", "design_pipeline/mock_assets/sample_input.png", "design_pipeline/mock_assets/master_composition.png", output_path)
    assert os.path.exists(output_path)
    assert result["score"] >= 90.0
