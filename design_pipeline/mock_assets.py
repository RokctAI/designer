import os
import requests
from PIL import Image
from io import BytesIO

def generate_mock_assets():
    print("Downloading master FedEx logo...")
    # Fetching using the requests library as instructed
    url = "https://1000logos.net/wp-content/uploads/2017/02/FedEx-Logo-500x313.png"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = response.content
    else:
        url = "https://logos-world.net/wp-content/uploads/2020/04/FedEx-Logo.png"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = response.content
        else:
            print("Failed to download image", response.status_code)
            return

    master_path = 'design_pipeline/mock_assets/master_composition.png'
    sample_path = 'design_pipeline/mock_assets/sample_input.png'

    # Save raw binary image locally
    with open(master_path, 'wb') as f:
        f.write(content)

    master = Image.open(master_path)
    if master.mode != 'RGBA':
        master = master.convert('RGBA')

    bg = Image.new('RGB', (800, 600), '#121212')
    w, h = master.size
    new_w = 400
    new_h = int(h * (new_w / w))
    master_resized = master.resize((new_w, new_h))

    center_x = (800 - new_w) // 2
    center_y = (600 - new_h) // 2
    bg.paste(master_resized, (center_x, center_y), master_resized)
    bg.save(master_path)

    sample = Image.new('RGB', (800, 600), '#121212')
    sample.paste(master_resized, (50, 100), master_resized)
    sample.save(sample_path)
    print("Assets generated.")

if __name__ == "__main__":
    generate_mock_assets()
