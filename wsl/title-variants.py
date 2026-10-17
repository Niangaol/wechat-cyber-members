"""Read-only OCR diagnostics for short Chinese titles."""
import io,json,sys
from pathlib import Path
from PIL import ImageOps
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wechat_ui import WeChatUI
ui=WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()))
im=ui.capture()
for box in [(283,20,700,61),(295,25,500,59)]:
    crop=ImageOps.grayscale(im.crop(box)).resize(((box[2]-box[0])*4,(box[3]-box[1])*4))
    for lang in ['chi_sim','chi_sim+eng']:
        for psm in [7,6]:
            out=io.BytesIO();crop.save(out,'PNG')
            text=ui.run(['tesseract','stdin','stdout','-l',lang,'--psm',str(psm)],out.getvalue()).decode().strip()
            print(json.dumps({'box':box,'lang':lang,'psm':psm,'text':text},ensure_ascii=False),flush=True)
