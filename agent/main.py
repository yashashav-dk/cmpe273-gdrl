import asyncio
import time

from decider import Decider
from decision_log import DecisionLog
from feature_extractor import FeatureExtractor
from metrics_client import PrometheusClient
from policy_writer import PolicyWriter
from predictor import HoltWintersPredictor

TICK_INTERVAL_SECONDS = 10


async def agent_loop(dry_run: bool = False) -> None:
    client = PrometheusClient()
    extractor = FeatureExtractor()
    predictor = HoltWintersPredictor()
    writer = PolicyWriter(log=DecisionLog(), dry_run=dry_run)
    decider = Decider(writer=writer)

    history = client.request_rate_range(window_minutes=30)
    predictor.warm_up(history)
    print(f"  predictor warmed up from {sum(len(v) for v in history.values())} data points")

    tick = 0
    while True:
        tick += 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{ts}] agent tick #{tick}")

        features = extractor.extract(client)
        predictions = predictor.update(features)
        top_users = client.top_user_share()
        decider.decide(features, predictions, top_users)

        for region, tiers in predictions.items():
            for tier, pred in tiers.items():
                actual = features[region].get(f"{tier}_rps", 0.0)
                tags = ""
                if pred.is_spike:
                    tags += "  *** SPIKE ***"
                if pred.anomaly:
                    tags += "  [ANOMALY]"
                print(
                    f"  {region}/{tier}: actual={actual:.1f} rps"
                    f"  predicted={pred.rps:.1f} rps{tags}"
                )

        await asyncio.sleep(TICK_INTERVAL_SECONDS)


def main(dry_run: bool = False) -> None:
    mode = " [DRY-RUN — no Redis writes]" if dry_run else ""
    print(f"gdrl AI traffic agent starting — tick every 10s (Holt-Winters + IsolationForest){mode}")
    asyncio.run(agent_loop(dry_run=dry_run))


if __name__ == "__main__":
    main()
