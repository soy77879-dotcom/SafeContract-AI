"""Validate actual black pixels and re-encode only a masked PNG. Python 3.9."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integrations.ocr_worker import load_images

def main():
    try:
        image=load_images([sys.argv[1]])[0]
        regions=json.loads(Path(sys.argv[2]).read_text())
        if not isinstance(regions,list) or not 1<=len(regions)<=1000:raise ValueError()
        for r in regions:
            if not isinstance(r,dict) or set(r)!={'x','y','width','height'} or any(type(v) is not int for v in r.values()):raise ValueError()
            x,y,w,h=(r[k] for k in ('x','y','width','height'))
            if min(x,y)<0 or min(w,h)<1 or x+w>image.width or y+h>image.height:raise ValueError()
            if any(extrema!=(0,0) for extrema in image.crop((x,y,x+w,y+h)).getextrema()):raise ValueError()
        image.save(sys.argv[3],format='PNG');return 0
    except Exception:return 1
if __name__=='__main__':sys.exit(main())
