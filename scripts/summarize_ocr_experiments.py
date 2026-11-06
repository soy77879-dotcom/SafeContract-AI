"""Create a compact measured-results report from an existing frozen evaluation JSON."""
import argparse
from collections import Counter
import json
from pathlib import Path

try:
    from .ocr_experiments import save_json
except ImportError:
    from ocr_experiments import save_json


def summarize(evaluation, output_dir):
    data=json.loads(evaluation.read_text(encoding='utf-8'))
    results=data['results']
    baseline=next(r for r in results if r['experiment_id']=='E00' and r['repeat']==0)
    br=baseline['metrics']['micro']['raw']['cer'];bn=baseline['metrics']['micro']['normalized']['cer']
    bc=baseline['error_analysis']['critical_difference_count']
    rows=[]
    for r in results:
        m=r['metrics']['micro'];n=m['normalized']['cer'];raw=m['raw']['cer']
        rows.append({'id':r['experiment_id'],'repeat':r['repeat'],'method':r['method'],'predict_options':r['predict_options'],
                     'raw_cer':raw,'normalized_cer':n,'ocr_seconds':r['ocr_seconds'],
                     'preprocessing_seconds':r['preprocessing_seconds'],
                     'normalized_relative_reduction_pct':(bn-n)/bn*100 if bn else None,
                     'critical_difference_count':r['error_analysis']['critical_difference_count'],
                     'low_confidence_lines':sum(e['confidence']<0.9 for v in r['assignment']['assigned'].values() for e in v),
                     'excluded_line_ids':[e['line_id'] for e in r['assignment']['excluded']],
                     'ambiguous_count':len(r['assignment']['ambiguous']),
                     'clause_cer':{cid:{mode:v[mode]['cer'] for mode in ['raw','normalized']} for cid,v in r['metrics']['clauses'].items()},
                     'source_result':r['source_result'],'source_result_sha256':r['source_result_sha256']})
    eligible=[r for r in rows if r['normalized_cer']<bn and r['raw_cer']<=br
              and r['critical_difference_count']<=bc and r['ambiguous_count']==0]
    best=min(eligible,key=lambda r:(r['normalized_cer'],r['raw_cer'],r['ocr_seconds'])) if eligible else rows[0]
    output_dir.mkdir(parents=True,exist_ok=True)
    output={'scope':'PDF page 2; C004-C019 only; one standard blank contract; known-layout geometry matching',
            'policy_version':data['policy_version'],'alignment_version':data['alignment_version'],
            'ground_truth_sha256':data['ground_truth_sha256'],'measurements':rows,
            'recommended_experiment':best['id'],
            'selection':'normalized CER lower, raw CER no worse, critical difference count no worse, no ambiguous line assignments',
            'baseline_error_analysis':baseline['error_analysis'],
            'recommended_error_analysis':next(r['error_analysis'] for r in results if r['experiment_id']==best['id']),
            'limitations':['single-page in-sample experiment, not held-out evaluation','no filled amounts or dates on blank form',
                           'critical difference count is a heuristic, not a legal meaning guarantee',
                           'confidence is not accuracy','geometry uses annotated GT regions, not production clause segmentation']}
    save_json(output_dir/'d7_ocr_results.json',output)
    headings=['# SafeContract AI D-7 OCR 성능 실험 보고서','',
     '## 1. 범위와 엔진','',
     'PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 / PaddleX 3.7.2 / PyMuPDF 1.26.5 / Python 3.9.6.',
     '기존 한국어 모델을 로컬 실행하며 이미지가 외부 OCR 서비스로 전송되지 않는다. 새 모델 설치나 백엔드 수정은 하지 않았다.',
     '탐지 `PP-OCRv5_server_det`, 인식 `korean_PP-OCRv5_mobile_rec`. 한국어 지원 및 기존 설치 모델을 재사용하기 위해 선정했다.',
     '입력은 기존 `tmp/ocr_test/contract_page2.png`(1190×1682). 원본 PDF 2쪽의 2배 렌더와 픽셀 단위 일치함을 확인했다.',
     'PDF 텍스트를 OCR 출력으로 사용하지 않았다. 실제 `PaddleOCR.predict`의 문자열·confidence·다각형 좌표를 보관했다.',
     '', '## 2. 평가 범위와 정렬','',
     'Ground Truth 19개 중 2쪽의 C004~C019 **16개**만 평가한다. PDF의 특약사항 제목과 하단 쪽수는 정답 범위 밖이며 제외 목록에 남긴다.',
     '기존 `ocr_evaluation.py`와 `normalization_policy.md`를 그대로 사용한다. 원문 CER와 공백 8종만 제거하는 정규화 CER를 모두 보고한다.',
     'PDF 좌표를 이미지 크기에 비례 변환하여 조항 영역에 대응시킨다. 문자열 유사도로 조항을 맞추거나 정답으로 OCR 문자를 교체하지 않는다.',
     '알려진 양식의 위치 정보를 이용한 평가다. 임의 계약서의 자동 조항 분리 성능을 측정한 것은 아니다.',
     '최초 임시 정렬(row-height 0.45)에서 표 라벨이 설명 뒤로 밀려 Raw 13.4069%, Normalized 3.7700%로 나왔다.',
     '원본 표 배치를 확인하여 라벨-설명 행 묶음 기준을 0.65로 고정했다. 모든 실험을 **같은 v2 정렬로 재평가**하며 이 정렬 개선을 이미지 전처리 효과에 포함하지 않는다.',
     '원시 결과 JSON의 초기 metrics는 보존한다. 이 보고서와 `evaluation_v2.json`이 공통 최종 비교 기준이다.',
     '', '## 3. 실측 결과','',
     '| 실험 | 방법 | Raw CER | Normalized CER | OCR 초 | 주요 표현 차이* |',
     '|---|---|---:|---:|---:|---:|']
    for r in rows:
        headings.append(f"| {r['id']} | {r['method']} {r['predict_options'] or ''} | {r['raw_cer']:.4%} | {r['normalized_cer']:.4%} | {r['ocr_seconds']:.2f} | {r['critical_difference_count']} |")
    headings += ['', '*주요 표현 차이: 조항별 주체·의무·부정 표현 등의 출현 횟수 및 숫자 토큰 배열 차이 건수. 법적 의미 판정이나 정식 정확도 지표가 아니다.',
     '시간은 `predict` 결과 생성 완료까지의 wall time이다. 모델 초기화·전처리·CER 계산은 제외하며 전처리 시간은 결과 JSON에 따로 보관한다.',
     '각 행은 1회 실행이며 통계적 속도 우위나 유의성을 주장하지 않는다. 최초 샌드박스 진단 실행(244.79초)은 비교표의 타이밍 표본에 섞지 않았다.',
     '', '## 4. 오류 분석','',
     '기준 OCR의 주요 오류: 원문자 번호 ①/②/③→1/2/3, `부담→부당`, 쉼표→마침표, 체크박스·글머리표 누락, 미기입 밑줄 누락 및 가운데점 종류 차이.',
     '공백 차이는 정규화 점수에서만 제외되며 숫자·부정 표현·기호는 그대로 평가한다. 표 읽기 순서 오류는 별도 정렬 검토로 구분했다.',
     '원화·보증금·월세 금액은 2쪽에 실측 대상이 없고 날짜·특약 금액은 미기입이므로 해당 조건 인식 정확도를 입증하지 않는다.',
     '원문/OCR 차이·정규화 문자 위치·페이지·조항·OCR 좌표와 confidence는 결과 JSON의 error_analysis에 기록했다. 진단 diff는 SequenceMatcher이며 CER 자체는 기존 Levenshtein 계산이다.',
     '', '## 5. 최종 권장 설정','',
     f"추천: **{best['id']} / {best['method']}**, predict 옵션 `{best['predict_options']}`.",
     f"기준 Normalized CER {bn:.4%} → {best['normalized_cer']:.4%}; 상대 감소율 {best['normalized_relative_reduction_pct']:.2f}%." if bn else '기준 CER=0이므로 상대 감소율은 계산하지 않는다.',
     '실측 개선이 없으면 기본 설정을 유지한다. 본 결과는 같은 페이지에서 설정을 선택한 결과로 독립 검증이 필요하다.',
     '', '## 6. 모델·방향·confidence 검토','',
     '사용자 기본 설정(lang=korean, 방향/왜곡/텍스트줄 방향 보정 False)을 유지했다. E05만 공식 지원 탐지 크기 옵션을 변경했다.',
     '기준 OCR 70개 선의 기울기 중앙값은 0°, 69개는 절댓값 0.3° 이내다. 시각적으로도 정방향 문서여서 기울기 보정 실험은 불필요로 미실행했다.',
     '문서 방향·왜곡 보정 모델도 이 정방향 PDF 렌더에서 필요성이 확인되지 않아 미실행했고 다운로드하지 않았다.',
     '설치된 3.7.0 코드에서 `korean_PP-OCRv3_mobile_rec` 대안은 확인했지만 새 모델 다운로드·비교는 미실행이다. PP-OCRv6의 한국어 지원을 임의로 가정하지 않았다.',
     '현 인식 모델 사전에는 ①·②·•·□·담·당이 있으나 ₩는 없다. 원화 인식 한계는 향후 1쪽/기입 계약서 평가에서 별도로 다뤄야 한다.',
     'confidence 0.9 미만은 검토 표시만 하며 삭제·자동 수정하지 않는다. 높은 confidence에도 문자 오류가 있어 사람 확인을 대체할 수 없다.',
     '', '## 7. 재현 방법','',
     '프로젝트 루트, 기존 .venv와 기존 두 모델 캐시를 사용한다. 모델 해시·실제 설정·패키지 버전은 run_metadata.json에 있다.',
     '기존 결과를 덮어쓰지 않도록 매번 새 출력 폴더를 지정한다.',
     '```bash',
     'PYTHONDONTWRITEBYTECODE=1 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True .venv/bin/python scripts/ocr_experiments.py --output tmp/ocr_experiments/new_run',
     'PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/ocr_experiments.py --rescore-run tmp/ocr_experiments/new_run --output tmp/ocr_experiments/new_run/evaluation_v2.json',
     'PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/summarize_ocr_experiments.py --evaluation tmp/ocr_experiments/new_run/evaluation_v2.json --output tmp/ocr_experiments/new_run/report',
     'PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p "test_ocr*.py" -v',
     '```','',
     '원본 이미지, baseline JSON/TXT, 실험별 이미지·결과·confidence·좌표·차이 목록은 `tmp/ocr_experiments/d7_run01/`에 보관한다.',
     '', '## 8. 한계와 다음 검증','',
     '이번 데이터는 단일 미기입 표준 양식의 깨끗한 렌더다. 촬영·그림자·회전·다른 폰트·실제 기입 금액·다른 계약서로 일반화되지 않는다.',
     '정답의 공백과 밑줄은 원래 PDF 레이아웃의 영향을 받아 Raw CER가 높을 수 있다. 원문을 수정하거나 정규화 규칙을 늘려 수치를 낮추지 않았다.',
     '다음 단계는 개인정보 없는 기입 합성 계약서와 촬영 열화 이미지의 독립 평가 세트를 확보하고, 숫자·부정 표현별 정확도 및 사용자 수정 흐름을 검증하는 것이다.',
     '', '## 9. 참고 근거','',
     '- [PaddleOCR 공식 OCR 파이프라인 문서](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)',
     '- 실제 3.7.0 옵션/한국어 모델 선택: 설치된 paddleocr/_pipelines/ocr.py 및 _common_args.py 확인.',
     '- 실제 인식 문자 사전: 로컬 korean_PP-OCRv5_mobile_rec/inference.yml 확인.','']
    headings += ['## 10. 조항별 Normalized CER','',
                 '| 조항 | Baseline | 권장 방식 |','|---|---:|---:|']
    for cid, scores in rows[0]['clause_cer'].items():
        headings.append(f"| {cid} | {scores['normalized']:.4%} | {best['clause_cer'][cid]['normalized']:.4%} |")
    headings += ['', 'C004는 수선 책임 표를 포함한다. C014~C019는 특약이며 빈칸 밑줄과 체크박스도 평가 대상이다.',
                 '', '## 11. 검증 및 제출 파일','',
                 '기존 평가 단위 테스트와 추가 좌표 매칭·보존 테스트는 tests/에 있다. 실제 실행 결과는 d7_validation.json에 별도 기록한다.',
                 'GitHub Desktop에 포함: scripts/ocr_experiments.py, scripts/summarize_ocr_experiments.py, tests/test_ocr_experiments.py, docs/d7_ocr_report.md, docs/d7_ocr_results.json, docs/d7_validation.json.',
                 '제외: tmp/ocr_experiments/, tmp/ocr_test/, 원본 PDF, .venv/, 모델 캐시. 기존 .gitignore를 유지한다.',
                 '권장 커밋 제목: feat: measure D-7 OCR baseline and preprocessing experiments',
                 '브랜치 전환, merge/pull/push/commit/PR 생성은 수행하지 않는다.', '']
    path=output_dir/'d7_ocr_report.md' 
    with path.open('x',encoding='utf-8') as f:f.write('\n'.join(headings))
    print(json.dumps({'recommended':best['id'],'rows':len(rows)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    summarize(args.evaluation,args.output)
