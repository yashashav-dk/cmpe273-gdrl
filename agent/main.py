import asyncio
import time

from feature_extractor import extract
from metrics_client import PrometheusClient

TICK_INTERVAL_SECONDS = 10


async def agent_loop() -> None:
    client = PrometheusClient()
    tick = 0
    while True:
        tick += 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{ts}] agent tick #{tick}")

        features = extract(client)
        for region, f in features.items():
            print(
                f"  {region}: free={f['free_rps']} rps  premium={f['premium_rps']} rps"
                f"  internal={f['internal_rps']} rps  rejection={f['rejection_rate']:.2%}"
            )

        await asyncio.sleep(TICK_INTERVAL_SECONDS)


def main() -> None:
    print("gdrl AI traffic agent starting — tick every 10s")
    asyncio.run(agent_loop())


if __name__ == "__main__":
    main()
