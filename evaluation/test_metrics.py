import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.metrics import evaluate_claims
from evaluation.run import (
    DATASET_PATH,
    evaluate_engine,
    load_dataset,
    local_extractor,
    main,
    sentence_baseline,
)


def claim(text="Paris is in France", start=0, **labels):
    return {
        "exact_text": text,
        "text_span": {"start": start, "end": start + len(text)},
        "claim_type": "factual",
        "objectively_checkable": True,
        "verification_status": "UNVERIFIED",
        **labels,
    }


class StrictMetricTests(unittest.TestCase):
    def test_duplicate_prediction_cannot_reuse_gold(self):
        result = evaluate_claims([claim()], [claim(), claim()])
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["exact_boundary_precision"], 0.5)
        self.assertEqual(result["exact_boundary_recall"], 1.0)
        self.assertEqual(len(result["extras"]), 1)

    def test_repeated_text_at_different_offsets_is_distinct(self):
        result = evaluate_claims([claim(), claim(start=20)], [claim(), claim(start=20)])
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["exact_boundary_f1"], 1.0)

    def test_partial_overlap_does_not_match(self):
        result = evaluate_claims([claim()], [claim("Paris is in")])
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["exact_boundary_f1"], 0.0)
        self.assertEqual(len(result["misses"]), 1)

    def test_all_empty_metrics_are_unavailable(self):
        result = evaluate_claims([], [])
        self.assertIsNone(result["exact_boundary_precision"])
        self.assertIsNone(result["exact_boundary_recall"])
        self.assertIsNone(result["exact_boundary_f1"])
        self.assertIsNone(result["false_supported_rate"])

    def test_missing_predictions_are_zero_recall(self):
        result = evaluate_claims([claim()], [])
        self.assertIsNone(result["exact_boundary_precision"])
        self.assertEqual(result["exact_boundary_recall"], 0.0)

    def test_empty_gold_with_extra_prediction_is_zero_precision(self):
        result = evaluate_claims([], [claim()])
        self.assertEqual(result["exact_boundary_precision"], 0.0)
        self.assertIsNone(result["exact_boundary_recall"])

    def test_labels_and_premature_support_are_separate_from_matching(self):
        result = evaluate_claims([claim()], [claim(claim_type="predictive", objectively_checkable=False, verification_status="SUPPORTED")])
        self.assertEqual(result["exact_boundary_f1"], 1.0)
        self.assertEqual(result["matched_category_accuracy"], 0.0)
        self.assertEqual(result["matched_checkability_accuracy"], 0.0)
        self.assertEqual(result["false_supported_count"], 1)
        self.assertEqual(len(result["label_errors"]), 1)

    def test_unclassified_baseline_does_not_get_label_credit(self):
        result = evaluate_claims([claim()], [claim(claim_type=None, objectively_checkable=None)])
        self.assertEqual(result["matched"], 1)
        self.assertIsNone(result["matched_category_accuracy"])


class EvaluationRunnerTests(unittest.TestCase):
    def test_service_failure_is_not_a_successful_empty_extraction(self):
        with patch("backend.verification.service.extract_response", return_value=SimpleNamespace(extraction_status="failed", claims=[])):
            with self.assertRaisesRegex(RuntimeError, "service reported"):
                local_extractor("Paris is in France.")

    def test_draft_dataset_spans_validate(self):
        dataset = load_dataset(DATASET_PATH)
        self.assertEqual(dataset["review_status"], "draft")
        self.assertEqual(len(dataset["cases"]), 32)
        self.assertEqual({case["split"] for case in dataset["cases"]}, {"dev", "heldout"})

    def test_baseline_preserves_decimal_and_offsets(self):
        source = "2.5 equals 2.5. Paris is in France."
        predicted = sentence_baseline(source)
        self.assertEqual(len(predicted), 2)
        self.assertEqual(predicted[0]["exact_text"], "2.5 equals 2.5")
        for item in predicted:
            self.assertEqual(source[item["text_span"]["start"]:item["text_span"]["end"]], item["exact_text"])

    def test_engine_failure_is_visible_and_counts_as_miss(self):
        def broken_engine(_source):
            raise ValueError("intentional fixture error")

        cases = [{"id": "broken", "split": "dev", "tags": [], "response_text": "Paris is in France", "claims": [claim()]}]
        result = evaluate_engine(cases, broken_engine)
        self.assertEqual(result["failed_case_count"], 1)
        self.assertEqual(result["metrics"]["exact_boundary_recall"], 0.0)
        self.assertIn("intentional fixture error", result["cases"][0]["error"])

    def test_modified_source_span_fails_closed(self):
        cases = [{"id": "bad-span", "split": "dev", "tags": [], "response_text": "Paris is in France", "claims": [claim()]}]
        result = evaluate_engine(cases, lambda _source: [claim("Tokyo is in Japan")])
        self.assertEqual(result["failed_case_count"], 1)
        self.assertEqual(result["metrics"]["matched"], 0)

    def test_cli_keeps_splits_separate_and_does_not_run_paid_baselines(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            self.assertEqual(main(["--engine", "baseline", "--split", "all", "--output", str(output)]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(set(report["splits"]), {"dev", "heldout"})
        self.assertEqual(report["splits"]["dev"]["sentence_baseline"]["case_count"], 20)
        self.assertEqual(report["splits"]["heldout"]["sentence_baseline"]["case_count"], 12)
        self.assertIn("Not run", report["unavailable_measurements"]["ordinary_llm_judge_baseline"])


if __name__ == "__main__":
    unittest.main()
