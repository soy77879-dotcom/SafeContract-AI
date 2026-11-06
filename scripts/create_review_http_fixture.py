"""Create an explicitly synthetic masked contract for local HTTP/browser tests."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]

def main():
    path=ROOT/'tmp/review_http/masked-contract.png'
    if path.exists():
        print('Synthetic fixture already exists; no overwrite performed.');return
    image=Image.new('RGB',(1600,900),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc',48)
    draw.rectangle((30,30,330,100),fill='black')
    lines=['주택임대차표준계약서','[계약내용]','제1조(수리 책임) 임대인은 수리비를 부담한다.',
           '제2조(보증금 반환) 임대인은 계약 종료 시 보증금을 반환한다.']
    for i,line in enumerate(lines):draw.text((50,180+i*140),line,font=font,fill='black')
    path.parent.mkdir(parents=True,exist_ok=True);image.save(path)
    print('Synthetic fixture created.')
if __name__=='__main__':main()
