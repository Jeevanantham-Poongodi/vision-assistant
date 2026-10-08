"""Small opt-in Gemini latency benchmark; requires GEMINI_API_KEY for live calls."""

from __future__ import annotations

import argparse
import statistics

from ai.gemini import answer_question


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=6.0)
    args = parser.parse_args()
    iterations = max(1, min(args.iterations, 20))

    durations: list[int] = []
    for iteration in range(iterations):
        result = answer_question(
            "What is in front of me?",
            mode="question",
            detections=[
                {
                    "class_name": "chair",
                    "spoken_name": "chair",
                    "category": "obstacle",
                    "direction": "center",
                    "distance_m": 1.2,
                    "motion": "stationary",
                    "risk_level": "high",
                }
            ],
            timeout_s=args.timeout,
        )
        durations.append(result["latency_ms"])
        print(
            f"{iteration + 1}/{iterations}: {result['source']} "
            f"{result['latency_ms']} ms — {result['answer']}"
        )

    print(f"Average latency: {statistics.mean(durations):.1f} ms")
    print(f"Median latency: {statistics.median(durations):.1f} ms")


if __name__ == "__main__":
    main()
