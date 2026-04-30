import asyncio
import time

from decider import Decider
from decision_log import DecisionLog
from feature_extractor import extract
from metrics_client import PrometheusClient
from policy_writer import PolicyWriter
from predictor import EWMAPredictor

TICK_INTERVAL_SECONDS = 10


async def agent_loop() -> None:
    client = PrometheusClient()
    predictor = EWMAPredictor(alpha=0.3)
    writer = PolicyWriter(log=DecisionLog())
    decider = Decider(writer=writer)

    history = client.request_rate_range(window_minutes=30)
    predictor.warm_up(history)
    print(f"  EWMA warmed up from {sum(len(v) for v in history.values())} data points")

    tick = 0
    while True:
        tick += 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{ts}] agent tick #{tick}")

        features = extract(client)
        predictions = predictor.update(features)
        top_users = client.top_user_share()
        decider.decide(features, predictions, top_users)

        for region, tiers in predictions.items():
            for tier, pred in tiers.items():
                actual = features[region].get(f"{tier}_rps", 0.0)
                spike_tag = "  *** SPIKE ***" if pred.is_spike else ""
                print(
                    f"  {region}/{tier}: actual={actual:.1f} rps"
                    f"  predicted={pred.rps:.1f} rps{spike_tag}"
                )

        await asyncio.sleep(TICK_INTERVAL_SECONDS)


def main() -> None:
    print("gdrl AI traffic agent starting — tick every 10s")
    asyncio.run(agent_loop())


if __name__ == "__main__":
    main()
