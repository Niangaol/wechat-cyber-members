"""OCR locate a button on a saved screenshot; prints its center."""
import io, json, subprocess, sys
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
ENV = dict(__import__('os').environ, DISPLAY=':99')
shot = ROOT/sys.argv[1]
targets = [t.upper() for t in sys.argv[2:]] or ['LOG IN', 'OK']
im = Image.open(shot).convert('RGB')
big = im.resize((im.width*2, im.height*2))
out = io.BytesIO(); big.save(out, 'PNG')
raw = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '11', 'tsv'],
                     input=out.getvalue(), capture_output=True, env=ENV, timeout=30
                     ).stdout.decode('utf-8', 'ignore')
hits = []
for line in raw.splitlines()[1:]:
    p = line.split('	')
    if len(p) < 12 or not p[11].strip():
        continue
    x, y, w, h = (int(v)//2 for v in p[6:10])
    hits.append({'t': p[11], 'center': [x + w//2, y + h//2]})
print(json.dumps({'words': hits}, ensure_ascii=False), flush=True)
for h in hits:
    if h['t'].strip().upper() in targets:
        print(json.dumps({'MATCH': h['t'], 'center': h['center']}, ensure_ascii=False), flush=True)
