"""Train the open-play shot location model from StatsBomb Open Data.

StatsBomb Open Data: https://github.com/hudl/open-data
Research use and redistribution require attribution to StatsBomb.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

from src.agents.xg_geometry import statsbomb_features


SOURCE_COMMIT = "4b73468fc5b0f1950f9f66fada70ad3a4f9327cb"
BASE = f"https://raw.githubusercontent.com/hudl/open-data/{SOURCE_COMMIT}/data"
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "agents" / "xg_model.json"


def fetch_json(path: str):
    with urlopen(f"{BASE}/{path}", timeout=30) as response:
        return json.load(response)


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, value))))


def brier(rows: list[tuple[tuple[float, float, float], int]], weights: list[float]) -> float:
    return sum((sigmoid(sum(w * v for w, v in zip(weights, x))) - y) ** 2 for x, y in rows) / len(rows)


def main() -> None:
    matches = fetch_json("matches/43/3.json")  # 2018 men's FIFA World Cup.
    match_ids = sorted(match["match_id"] for match in matches)

    def read_match(match_id: int):
        rows = []
        for event in fetch_json(f"events/{match_id}.json"):
            if event.get("type", {}).get("name") != "Shot":
                continue
            shot = event["shot"]
            if shot.get("type", {}).get("name") != "Open Play":
                continue
            location = event.get("location")
            if not location or len(location) < 2:
                continue
            rows.append((statsbomb_features(location[0], location[1]), int(shot["outcome"]["name"] == "Goal")))
        return match_id, rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        by_match = dict(pool.map(read_match, match_ids))
    train = [row for index, match_id in enumerate(match_ids) if index % 4 != 0 for row in by_match[match_id]]
    test = [row for index, match_id in enumerate(match_ids) if index % 4 == 0 for row in by_match[match_id]]
    if not train or not test:
        raise RuntimeError("StatsBomb source returned no training or test shots")

    weights = [-2.0, 0.0, 0.0]
    for _ in range(4000):
        gradient = [0.0, 0.0, 0.0]
        for values, goal in train:
            difference = sigmoid(sum(w * v for w, v in zip(weights, values))) - goal
            for i in range(3):
                gradient[i] += difference * values[i]
        for i in range(3):
            gradient[i] = gradient[i] / len(train) + (0.001 * weights[i] if i else 0.0)
            weights[i] -= 0.15 * gradient[i]

    baseline_rate = sum(goal for _, goal in train) / len(train)
    baseline_brier = sum((baseline_rate - goal) ** 2 for _, goal in test) / len(test)
    result = {
        "model": "open_play_location_logistic_v1",
        "source": "StatsBomb Open Data",
        "source_url": "https://github.com/hudl/open-data",
        "source_commit": SOURCE_COMMIT,
        "competition": "2018 FIFA World Cup, 64 matches",
        "features": ["intercept", "distance_m/20", "goal_angle_radians"],
        "coefficients": [round(weight, 8) for weight in weights],
        "train_shots": len(train),
        "test_shots": len(test),
        "test_brier": round(brier(test, weights), 6),
        "constant_baseline_test_brier": round(baseline_brier, 6),
        "scope": "Open-play shots; location only. No goalkeeper, defensive pressure, body part, or calibration across leagues.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
