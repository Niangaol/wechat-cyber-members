"""Read-only OCR variants for the visible @ bubble."""
import io, json, sys
from pathlib import Path
from PIL import Image, ImageOps
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from wechat_ui import WeChatUI
from visual_parse import extract_messages
ui = WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()))
im = ui.capture()
cands = [m for m in extract_messages(im) if m['direction'] == 'in' and '@' in ''.join(
    t for t, x, y, w, h in [(w2[0], w2[1], w2[2], w2[3], w2[4]) for w2 in []] ) ] if False else []
for m in extract_messages(im):
    if m['direction'] != 'in':
        continue
    x1, y1, x2, y2 = m['bbox']
    crop = im.crop((x1, y1, x2, y2))
    variants = {}
    gray = ImageOps.grayscale(crop)
    variants['gray4x'] = gray.resize((gray.width*4, gray.height*4))
    big = gray.resize((gray.width*6, gray.height*6))
    variants['gray6x'] = big
    variants['bw6x'] = big.point(lambda p: 0 if p < 150 else 255)
    for name, img in variants.items():
        out = io.BytesIO(); img.save(out, 'PNG')
        for psm in (7, 6):
            text = ui.run(['tesseract', 'stdin', 'stdout', '-l', 'chi_sim', '--psm', str(psm)],
                          out.getvalue()).decode('utf-8', 'ignore').strip()
            print(json.dumps({'bbox': m['bbox'], 'variant': name, 'psm': psm, 'text': text},
                             ensure_ascii=False), flush=True)
