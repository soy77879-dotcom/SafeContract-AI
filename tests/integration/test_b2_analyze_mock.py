
"""B-2 4번: 분석 API 요청·응답 계약 Mock 검증."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.schemas import AnalyzeRequest, AnalyzeResponse
from integrations.adapter import analyze_request
from integrations.review_app import app


def make_request():
    """개인정보 없는 분석 요청을 생성한다."""
    return {
        "document_id": "mock-document",
        "clauses": [
            {
                "clause_id": "C001",
                "page": 1,
                "text": "보증금 반환 관련 테스트 조항",
            }
        ],
    }


def make_response():
    """현재 AnalyzeResponse 스키마에 맞는 가상 결과를 만든다."""
    return {
        "document_id": "mock-document",
        "status": "completed",
        "results": [
            {
                "clause_id": "C001",
                "risk_type": "deposit_return",
                "risk_status": "potential_risk",
                "evidence": "보증금 반환 관련 테스트 조항",
                "reason": "반환 조건에 대한 추가 확인이 필요합니다.",
                "possible_disadvantage": "보증금 반환이 지연될 가능성이 있습니다.",
                "question": "보증금 반환 시점은 언제인가요?",
                "recommended_action": "반환 시점과 조건을 확인하세요.",
            }
        ],
        "warnings": [],
    }


class FakeLedger:
    def __init__(self, approved):
        self.is_approved = approved

    def approved(self, data):
        return self.is_approved


class TestAnalyzeMock(unittest.TestCase):

    def test_valid_request(self):
        """정상적인 분석 요청은 스키마를 통과한다."""
        result = AnalyzeRequest.model_validate(make_request())
        self.assertEqual(result.document_id, "mock-document")

    def test_valid_response(self):
        """가상 위험 분석 결과는 응답 스키마를 통과한다."""
        result = AnalyzeResponse.model_validate(make_response())
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.results), 1)

    def test_invalid_response(self):
        """필수 설명이 누락되면 응답 검증에 실패한다."""
        response = make_response()
        del response["results"][0]["possible_disadvantage"]

        with self.assertRaises(ValidationError):
            AnalyzeResponse.model_validate(response)

    def test_review_approval_passed_to_engine(self):
        """사용자 검토 승인이 분석 엔진에 전달되는지 확인한다."""
        request = make_request()
        response = make_response()

        with patch(
            "integrations.adapter.analyze_document",
            return_value={"mock": True},
        ) as engine, patch(
            "integrations.adapter.to_api",
            return_value=response,
        ):
            result = analyze_request(request, FakeLedger(True))

        self.assertEqual(result.status, "completed")
        self.assertEqual(engine.call_args.args[1], ["C001"])

    def test_unapproved_request_not_marked_reviewed(self):
        """미승인 조항은 확인 완료 목록에 포함되지 않는다."""
        with patch(
            "integrations.adapter.analyze_document",
            return_value={"mock": True},
        ) as engine, patch(
            "integrations.adapter.to_api",
            return_value=make_response(),
        ):
            analyze_request(make_request(), FakeLedger(False))

        self.assertEqual(engine.call_args.args[1], [])

    def test_http_analyze_is_blocked(self):
        """기존 개발용 분석 API의 차단 정책을 확인한다."""
        with TestClient(
            app,
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        ) as client:
            session = client.get("/api/session")
            self.assertEqual(session.status_code, 200)

            response = client.post(
                "/api/analyze",
                headers={
                    "origin": "http://localhost",
                    "x-review-csrf": session.json()["csrf_token"],
                },
                json=make_request(),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["code"],
            "PRIVACY_CHECK_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
