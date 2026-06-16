import os
import json
from typing import Dict, Tuple, Any
from PIL import Image, ImageChops, ImageDraw, ImageStat, ImageFont

class DesignEngine:
    def extract_element_coordinates(self, image: Image.Image) -> Dict[str, list[int]]:
        raise NotImplementedError

class GeminiDesignEngine(DesignEngine):
    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)

    def extract_element_coordinates(self, image: Image.Image) -> Dict[str, list[int]]:
        prompt = (
            "Analyze the given image and extract the bounding boxes for the 'icon' layer and the 'text' layer. "
            "Output the coordinates as a JSON object strictly following this structure: "
            '{"icon": [ymin, xmin, ymax, xmax], "text": [ymin, xmin, ymax, xmax]}'
        )
        response = self.client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, image]
        )
        try:
            text = response.text
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
            return json.loads(text)
        except Exception as e:
            raise RuntimeError(f"Failed to parse Gemini output: {response.text}") from e

class MockDesignEngine(DesignEngine):
    def extract_element_coordinates(self, image: Image.Image) -> Dict[str, list[int]]:
        # Hardcoded realistic coordinates matching our mock assets
        return {
            "icon": [475, 509, 1023, 1537],
            "text": [1023, 509, 1572, 1537]
        }

def get_engine() -> DesignEngine:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return GeminiDesignEngine(api_key=api_key)
    else:
        return MockDesignEngine()

def extract_element_coordinates(image: Image.Image) -> Dict[str, list[int]]:
    engine = get_engine()
    return engine.extract_element_coordinates(image)

def slice_image(image: Image.Image, coords: Dict[str, list[int]]) -> Dict[str, Image.Image]:
    layers = {}
    for layer_name, box in coords.items():
        ymin, xmin, ymax, xmax = box
        cropped = image.crop((xmin, ymin, xmax, ymax))
        layers[layer_name] = cropped
    return layers

def typography_engine(industry_vertical: str) -> str:
    matrix = {"tech": "sans-serif", "finance": "serif", "creative": "DejaVuSans"}
    return matrix.get(industry_vertical.lower(), "DejaVuSans")

def image_match_score(img1: Image.Image, img2: Image.Image) -> float:
    if img1.size != img2.size:
        img2 = img2.resize(img1.size)
    diff = ImageChops.difference(img1.convert("RGB"), img2.convert("RGB"))
    stat = ImageStat.Stat(diff)
    total_diff = sum(stat.sum)
    max_diff = diff.width * diff.height * 3 * 255
    match_ratio = 1.0 - (total_diff / max_diff) if max_diff > 0 else 1.0
    return match_ratio * 100.0

def optimize_layout_loop(
    cropped_icon: Image.Image, text_string: str, target_font: str, master_composition: Image.Image,
    offset_x: int = -50, offset_y: int = -50, margin: int = 0, iteration: int = 0, max_iterations: int = 100
) -> Tuple[Image.Image, float, Dict[str, int]]:
    width, height = master_composition.size
    canvas = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype(f"{target_font}.ttf", size=60)
    except IOError:
        font = ImageFont.load_default()

    text_bbox = draw.textbbox((0, 0), text_string, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    total_height = cropped_icon.height + margin + text_height
    start_y = (height - total_height) // 2
    base_icon_x = (width - cropped_icon.width) // 2
    base_icon_y = start_y
    base_text_x = (width - text_width) // 2
    base_text_y = base_icon_y + cropped_icon.height + margin

    icon_x = base_icon_x + offset_x
    icon_y = base_icon_y + offset_y
    text_x = base_text_x + offset_x
    text_y = base_text_y + offset_y

    if cropped_icon.mode == 'RGBA':
        canvas.paste(cropped_icon, (icon_x, icon_y), cropped_icon)
    else:
        canvas.paste(cropped_icon, (icon_x, icon_y))
    draw.text((text_x, text_y), text_string, fill='#3357FF', font=font)

    score = image_match_score(canvas, master_composition)
    if score >= 90.0 or iteration >= max_iterations:
        return canvas, score, {"offset_x": offset_x, "offset_y": offset_y, "margin": margin}

    best_score = score
    best_step = (0, 0, 0)
    step_size = 10
    adjustments = [(step_size, 0, 0), (-step_size, 0, 0), (0, step_size, 0), (0, -step_size, 0), (0, 0, step_size), (0, 0, -step_size)]

    for dx, dy, dm in adjustments:
        test_canvas = Image.new('RGB', (width, height), color='white')
        test_draw = ImageDraw.Draw(test_canvas)

        test_margin = margin + dm
        test_total_height = cropped_icon.height + test_margin + text_height
        test_start_y = (height - test_total_height) // 2
        test_icon_x = base_icon_x + offset_x + dx
        test_icon_y = test_start_y + offset_y + dy
        test_text_x = base_text_x + offset_x + dx
        test_text_y = test_start_y + cropped_icon.height + test_margin + offset_y + dy

        if cropped_icon.mode == 'RGBA':
            test_canvas.paste(cropped_icon, (test_icon_x, test_icon_y), cropped_icon)
        else:
            test_canvas.paste(cropped_icon, (test_icon_x, test_icon_y))
        test_draw.text((test_text_x, test_text_y), text_string, fill='#3357FF', font=font)

        test_score = image_match_score(test_canvas, master_composition)
        if test_score > best_score:
            best_score = test_score
            best_step = (dx, dy, dm)

    if best_score > score:
        dx, dy, dm = best_step
        return optimize_layout_loop(
            cropped_icon, text_string, target_font, master_composition,
            offset_x + dx, offset_y + dy, margin + dm, iteration + 1, max_iterations
        )
    return canvas, score, {"offset_x": offset_x, "offset_y": offset_y, "margin": margin}

def run_pipeline(config_json_path: str, input_image_path: str, master_composition_path: str, output_path: str):
    with open(config_json_path, 'r') as f:
        config = json.load(f)
    company_name = config.get("company_name", "Default Co.")
    industry_vertical = config.get("industry_vertical", "tech")
    target_dimensions = config.get("target_layout_dimensions", {"width": 800, "height": 600})

    input_image = Image.open(input_image_path)
    master_composition = Image.open(master_composition_path)
    coords = extract_element_coordinates(input_image)
    layers = slice_image(input_image, coords)

    target_font = typography_engine(industry_vertical)
    icon = layers["icon"]
    # Scale icon if it's too large for the master composition
    max_icon_width = master_composition.width * 0.8
    max_icon_height = master_composition.height * 0.6
    if icon.width > max_icon_width or icon.height > max_icon_height:
        scale = min(max_icon_width / icon.width, max_icon_height / icon.height)
        new_width = int(icon.width * scale)
        new_height = int(icon.height * scale)
        icon = icon.resize((new_width, new_height), Image.Resampling.LANCZOS)

    canvas, score, params = optimize_layout_loop(
        cropped_icon=icon, text_string=company_name, target_font=target_font, master_composition=master_composition
    )

    if canvas.size != (target_dimensions["width"], target_dimensions["height"]):
        canvas = canvas.resize((target_dimensions["width"], target_dimensions["height"]))
    canvas.save(output_path)
    return {"score": score, "params": params, "font": target_font, "company_name": company_name}
