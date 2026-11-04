"""No-model tests for T4 metrics, completeness, and old-command compatibility."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import known_eval
import known_eval_dual as dual
import run_experiment


class DualEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lotte-dual-test-")
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "experiments").mkdir()
        self.truth = {f"s{i}": {"category": "맥주" if i < 4 else "탄산",
                                "value": {"a": 60, "b": 30, "c": 10}} for i in range(5)}
        (self.root / "config/truth.json").write_text(json.dumps(self.truth))
        self.patches = [patch.object(m, "ROOT", self.root) for m in (known_eval, dual, run_experiment)]
        for p in self.patches:
            p.start()
        self.rows = [{"uuid": f"p{i}", "rep": 0, "named": True,
                      "usual": "a" if i < 6 else "b" if i < 9 else "c",
                      "choice": "c" if i < 6 else "b" if i < 9 else "a",
                      "weekly_qty": i % 3 + 1} for i in range(10)]
        self.write_tag("fixture")

    def tearDown(self):
        for p in self.patches[::-1]:
            p.stop()
        self.tmp.cleanup()

    def write_tag(self, tag, rows=None, named=True):
        out = self.root / "results" / tag
        out.mkdir(parents=True, exist_ok=True)
        for sid in self.truth:
            (out / f"{sid}{'_named' if named else ''}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in (rows if rows is not None else self.rows)) + "\n")
        (out / "settings.json").write_text(json.dumps({"model": "fixture:no-model", "batch": 5}))

    def evaluate(self, tag="fixture"):
        return dual.evaluate(tag, "config/truth.json", 10)

    def test_both_metrics_equal_preserved_evaluator(self):
        self.write_tag("fixture", [dict(r, named=False) for r in self.rows], named=False)
        actual = self.evaluate()
        self.assertEqual(actual["metrics"]["choice"], known_eval.evaluate("fixture", "config/truth.json"))
        projected = [dict(r, choice=r["usual"]) for r in self.rows]
        self.write_tag("usual_projection", projected)
        self.write_tag("usual_projection", [dict(r, named=False) for r in projected], named=False)
        self.assertEqual(actual["metrics"]["usual"], known_eval.evaluate("usual_projection", "config/truth.json"))

    def test_primary_usual_wins_even_if_choice_fails(self):
        result = self.evaluate()
        self.assertEqual(result["decision"]["status"], "pass")
        self.assertEqual(result["decision"]["last_matches"], 5)
        self.assertEqual(result["metrics"]["choice"][dual.SELECTION]["last_match_rate"], 0)
        self.assertIn("보조choice", dual.ledger_metric(result))

    def test_bad_usual_is_fail_even_if_choice_passes(self):
        self.write_tag("fixture", [dict(r, usual=r["choice"], choice=r["usual"]) for r in self.rows])
        self.assertEqual(self.evaluate()["decision"]["status"], "fail")

    def test_legacy_usual_missing_remains_unknown(self):
        legacy = [{k: v for k, v in r.items() if k != "usual"} for r in self.rows]
        self.write_tag("fixture", legacy)
        result = self.evaluate()
        self.assertEqual(result["decision"]["status"], "unknown")
        self.assertEqual(result["metrics"]["usual"], {})
        self.assertEqual(result["metrics"]["choice"], known_eval.evaluate("fixture", "config/truth.json"))

    def test_partial_rows_are_unknown(self):
        self.write_tag("fixture", self.rows[:-1])
        self.assertEqual(self.evaluate()["decision"]["status"], "unknown")

    def test_duplicate_person_is_unknown(self):
        self.write_tag("fixture", self.rows[:-1] + [self.rows[0]])
        self.assertIn("s0:duplicate_uuid", self.evaluate()["errors"])

    def test_missing_shelf_is_unknown(self):
        (self.root / "results/fixture/s4_named.jsonl").unlink()
        result = self.evaluate()
        self.assertEqual(result["decision"]["status"], "unknown")
        self.assertIn("s4:file_missing", result["errors"])

    def test_invalid_json_is_not_silently_dropped(self):
        with (self.root / "results/fixture/s0_named.jsonl").open("a") as f:
            f.write("broken\n")
        result = self.evaluate()
        self.assertEqual(result["decision"]["status"], "unknown")
        self.assertNotIn("s0", result["metrics"]["usual"][dual.SELECTION]["shelves"])

    def test_invalid_field_rejects_complete_decision(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["choice"] = "not_a_product"
        self.write_tag("fixture", rows)
        self.assertEqual(self.evaluate()["decision"]["status"], "unknown")

    def spec(self, name="fixture", flags=None):
        spec = {"name": name, "n": 10, "sets_file": "config/sets.json",
                "truth_file": "config/truth.json", "flags": flags or [], "pass_rule": "usual 사전 기준"}
        (self.root / "experiments/spec.json").write_text(json.dumps(spec))
        return spec

    def invoke_runner(self, module=run_experiment, returncode=0):
        with patch.object(sys, "argv", ["run_experiment.py", "experiments/spec.json"]), \
             patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], returncode)) as call, \
             contextlib.redirect_stdout(io.StringIO()):
            module.main()
        return call

    def test_t4_runner_writes_primary_and_secondary(self):
        self.spec(flags=["--familiar-incumbents", "--batch", "5"])
        call = self.invoke_runner()
        self.assertFalse(call.call_args.kwargs["check"])
        result = json.loads((self.root / "results/fixture/known_eval_dual.json").read_text())
        self.assertEqual(result["decision"]["status"], "pass")
        report = (self.root / "results/fixture/report.md").read_text()
        self.assertIn("주 지표 · 평소 구매 (usual)", report)
        self.assertIn("보조 지표 · 이번 선택 (choice)", report)
        self.assertIn("주판정usual=pass", (self.root / "experiments/ledger.tsv").read_text())

    def test_t4_partial_runner_records_unknown_and_nonzero(self):
        self.spec(flags=["--familiar-incumbents"])
        self.write_tag("fixture", self.rows[:-1])
        with self.assertRaises(SystemExit) as ex:
            self.invoke_runner()
        self.assertNotEqual(ex.exception.code, 0)
        self.assertIn("주판정usual=unknown", (self.root / "experiments/ledger.tsv").read_text())

    def test_t4_nonzero_simulation_is_never_complete(self):
        self.spec(flags=["--familiar-incumbents"])
        with self.assertRaises(SystemExit):
            self.invoke_runner(returncode=2)
        result = json.loads((self.root / "results/fixture/known_eval_dual.json").read_text())
        self.assertIn("simulate_exit:2", result["errors"])
        self.assertEqual(result["decision"]["status"], "unknown")

    def test_t4_rejects_primary_change_before_simulation(self):
        spec = self.spec(flags=["--familiar-incumbents"])
        spec["primary_metric"] = "choice"
        (self.root / "experiments/spec.json").write_text(json.dumps(spec))
        with patch.object(run_experiment.subprocess, "run") as call, \
             patch.object(sys, "argv", ["run_experiment.py", "experiments/spec.json"]), self.assertRaises(SystemExit):
            run_experiment.main()
        call.assert_not_called()

    def test_default_runner_matches_saved_original_byte_for_byte(self):
        backup = Path(__file__).resolve().parents[3] / "wiki/projects/lotte-ax-2026-returns/2026-11-04-T4/before/run_experiment.py"
        if not backup.exists():
            self.skipTest("Original run_experiment backup unavailable outside this workspace")
        spec = importlib.util.spec_from_file_location("preserved_run_experiment", backup)
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        original.ROOT = self.root
        self.spec()
        self.invoke_runner(original)
        before = {p: (self.root / p).read_text() for p in ["results/fixture/report.md", "experiments/ledger.tsv"]}
        (self.root / "experiments/ledger.tsv").unlink()
        with patch.object(dual, "evaluate", side_effect=AssertionError("Legacy path must not call dual")):
            call = self.invoke_runner()
        self.assertTrue(call.call_args.kwargs["check"])
        after = {p: (self.root / p).read_text() for p in before}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
