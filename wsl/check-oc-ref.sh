#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 -m py_compile src/imagegen.py src/resident.py && echo COMPILE_OK
python3 - <<'PY'
import sys
sys.path.insert(0, 'src')
from imagegen import oc_prefix, _ref_image_part, OC_REF
print("PREFIX:", oc_prefix()[:150])
part = _ref_image_part(OC_REF)
print("REF_PART_OK:", part is not None, "b64_len:", len(part["image"]) if part else 0)
print("MISSING:", _ref_image_part("/tmp/nope.png"))
PY
