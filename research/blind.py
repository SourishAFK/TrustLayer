"""Create a reproducible labelling CSV and a separate, private response-ID map."""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from research.common import (
    BLIND_FIELDS,
    RESPONSE_FIELDS,
    atomic_write,
    digest,
    json_text,
    read_csv,
    read_scenarios,
    study_lock,
    write_csv,
)


def create_blind(run, output, seed, *, allow_partial=False):
    run, output = Path(run).resolve(), Path(output).resolve()
    with study_lock(run):
        manifest = json.loads((run / "private" / "manifest.json").read_text(encoding="utf-8"))
        source = run / "private" / "scenarios.csv"
        if digest(source.read_bytes()) != manifest["scenarios_sha256"]:
            raise ValueError("Scenario snapshot was modified after collection.")
        scenarios = {row["scenario_id"]: row for row in read_scenarios(source)}
        rows = read_csv(run / "responses.csv", RESPONSE_FIELDS, exact=True)
        if not rows:
            raise ValueError("There are no collected responses to blind.")
        models = {m["name"]: m for m in manifest["config"]["models"] if m.get("enabled", True)}
        expected_count = len(scenarios) * 2 * len(models)
        seen = set()
        for row in rows:
            sid, framing, name = row["scenario_id"], row["framing"], row["model"]
            if sid not in scenarios or framing not in {"loaded", "neutral"} or name not in models:
                raise ValueError("Response metadata does not match this study.")
            expected_id = digest(json_text([manifest["study_id"], sid, framing, name]).encode())
            if row["response_id"] != expected_id or expected_id in seen:
                raise ValueError("Duplicate or unexpected response_id.")
            seen.add(expected_id)
            receipt = run / "private" / "receipts" / f"{expected_id}.csv"
            if read_csv(receipt, RESPONSE_FIELDS, exact=True) != [row]:
                raise ValueError("responses.csv differs from its saved receipt; resume collection to rebuild it.")
            prompt = scenarios[sid][f"{framing}_prompt"]
            params = json.loads(row["generation_params"])
            if params.get("prompt_sha256") != digest(prompt.encode()):
                raise ValueError("Prompt mismatch; refusing to pair an answer with the wrong question.")
        if len(rows) != expected_count and not allow_partial:
            raise ValueError(f"Only {len(rows)}/{expected_count} responses exist. Finish collection or explicitly use --allow-partial.")
        rows.sort(key=lambda row: row["response_id"])
        random.Random(seed).shuffle(rows)
        blind_rows, mapping = [], []
        for index, row in enumerate(rows, 1):
            blind_id = f"B{index:05d}"
            blind_rows.append({"blind_id": blind_id,
                               "user_prompt": scenarios[row["scenario_id"]][row["framing"] + "_prompt"],
                               "ai_response": row["response_text"], "verdict": "",
                               "confidence_1_to_5": "", "reasoning": ""})
            mapping.append({"blind_id": blind_id, "response_id": row["response_id"]})
        # Never overwrite a co-author's labels or silently change an existing assignment.
        output.mkdir(parents=True, exist_ok=False)
        write_csv(output / "private" / "mapping.csv", ["blind_id", "response_id"], mapping)
        metadata = {"seed": seed, "shuffle": "Python random.Random(seed).shuffle, sorted response_id input",
                    "python_version": sys.version, "study_id": manifest["study_id"],
                    "responses_sha256": digest((run / "responses.csv").read_bytes()),
                    "rows": len(rows), "expected_rows": expected_count, "partial": len(rows) != expected_count,
                    "text_policy": "Responses unchanged, including refusals, truncation and self-identification."}
        atomic_write(output / "private" / "blinding_metadata.json", json_text(metadata).encode())
        write_csv(output / "share" / "blind_labels.csv", BLIND_FIELDS, blind_rows)
        atomic_write(output / "READY", b"Share only share/blind_labels.csv. Keep private/ with the study coordinator.\n")
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Collection output directory")
    parser.add_argument("--out", type=Path, required=True, help="New, unused blinding directory")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--allow-partial", action="store_true", help="Include available responses despite missing models/rows")
    args = parser.parse_args(argv)
    count = create_blind(args.run, args.out, args.seed, allow_partial=args.allow_partial)
    print(f"Prepared {count} rows with seed {args.seed}.")
    print(f"Share only: {(args.out / 'share' / 'blind_labels.csv').resolve()}")
    print(f"Keep private: {(args.out / 'private').resolve()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, csv.Error) as exc:
        print(f"Cannot prepare labels: {exc}", file=sys.stderr)
        sys.exit(1)
