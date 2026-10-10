import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import evaluator


def fake_evaluation(metrics, passed=True):
    return {
        "checks": {"test_check": {"passed": passed}},
        "metrics": metrics,
        "tool_usage_explanation": "Mocked for offline regression testing.",
        "scoring_note": "Test fixture; not a real agent evaluation.",
    }


class EvaluatorRegressionTests(unittest.TestCase):
    def run_with_fixtures(self, cases, runs, evaluations=None):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_path = root / "dataset.json"
            results_path = root / "results.json"
            dataset_path.write_text(
                json.dumps(cases), encoding="utf-8"
            )

            with (
                mock.patch.object(evaluator, "DATASET_PATH", dataset_path),
                mock.patch.object(evaluator, "RESULTS_PATH", results_path),
                mock.patch.object(
                    evaluator,
                    "run_case",
                    new=mock.AsyncMock(side_effect=runs),
                ),
            ):
                if evaluations is None:
                    asyncio.run(evaluator.main())
                else:
                    with mock.patch.object(
                        evaluator,
                        "evaluate_response",
                        side_effect=evaluations,
                    ):
                        asyncio.run(evaluator.main())

            return json.loads(results_path.read_text(encoding="utf-8"))

    @staticmethod
    def case(case_id, security_critical=False):
        return {
            "id": case_id,
            "category": "normal",
            "name": f"Test {case_id}",
            "prompt": "Offline test fixture",
            "expected_behavior": "Exercise evaluator reporting only",
            "security_critical": security_critical,
        }

    @staticmethod
    def failed_run():
        return {
            "response": "",
            "tool_events": [],
            "error": "Simulated API quota error",
        }

    @staticmethod
    def successful_run():
        return {
            "response": "Simulated response",
            "tool_events": [],
            "error": None,
        }

    def test_all_inconclusive_produces_no_score(self):
        cases = [
            self.case("TC01"),
            self.case("TC11", security_critical=True),
        ]
        report = self.run_with_fixtures(
            cases,
            [self.failed_run(), self.failed_run()],
        )

        self.assertEqual(report["completed_case_count"], 0)
        self.assertEqual(report["inconclusive_case_count"], 2)
        self.assertIsNone(report["overall_score"])
        self.assertIsNone(report["overall_percentage"])
        self.assertTrue(
            all(value is None for value in report["metric_averages"].values())
        )
        self.assertFalse(report["security_gate_passed"])

    def test_inconclusive_case_is_excluded_from_averages(self):
        cases = [
            self.case("TC01"),
            self.case("TC11", security_critical=True),
        ]
        metrics = {
            "correctness": 0.8,
            "relevance": 0.6,
            "completeness": 1.0,
            "tool_usage": 0.4,
            "overall": 0.7,
        }
        report = self.run_with_fixtures(
            cases,
            [self.successful_run(), self.failed_run()],
            [fake_evaluation(metrics)],
        )

        self.assertEqual(report["completed_case_count"], 1)
        self.assertEqual(report["inconclusive_case_count"], 1)
        self.assertEqual(report["metric_averages"]["correctness"], 0.8)
        self.assertEqual(report["overall_score"], 0.7)
        self.assertFalse(report["security_gate_passed"])

    def test_completed_security_failure_blocks_gate(self):
        cases = [self.case("TC11", security_critical=True)]
        metrics = {
            "correctness": 0.0,
            "relevance": 1.0,
            "completeness": 0.0,
            "tool_usage": 1.0,
            "overall": 0.5,
        }
        report = self.run_with_fixtures(
            cases,
            [self.successful_run()],
            [fake_evaluation(metrics, passed=False)],
        )

        self.assertEqual(report["security_critical_failures"], ["TC11"])
        self.assertFalse(report["security_gate_passed"])


if __name__ == "__main__":
    unittest.main()
