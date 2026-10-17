"""Read-only comparison of OCR preprocessing variants on live bubbles."""
import io, json, sys
from pathlib import Path
from PIL import Image, ImageOps
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from wechat_ui import WeChatUI
from visual_parse import extract_messages
ui = WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()))
im = ui.capture()
for m in extract_messages(im):
    x1, y1, x2, y2 = m['bbox']
    crop = im.crop((x1, y1, x2, y2))
    gray = ImageOps.grayscale(crop)
    variants = {
        'gray4x': gray.resize((gray.width*4, gray.height*4)),
        'bw4x150': gray.resize((gray.width*4, gray.height*4)).point(lambda p: 0 if p < 150 else 255),
        'bw4x180': gray.resize((gray.width*4, gray.height*4)).point(lambda p: 0 if p < 180 else 255),
        'bw6x150': gray.resize((gray.width*6, gray.height*6)).point(lambda p: 0 if p < 150 else 255),
        'bw6x200': gray.resize((gray.width*6, gray.height*6)).point(lambda p: 0 if p < 200 else 255),
        'rgb4x': crop.resize((crop.width*4, crop.height*4)),
    }
    row = {'bbox': m['bbox']}
    for name, img in variants.items():
        out = io.BytesIO(); img.save(out, 'PNG')
        text = ui.run(['tesseract', 'stdin', 'stdout', '-l', 'chi_sim+eng', '--psm', '7'],
                      out.getvalue(), timeout=25).decode('utf-8', 'ignore').strip()
        row[name] = text
    print(json.dumps(row, ensure_ascii=False), flush=True)
