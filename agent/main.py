import asyncio
import time

from metrics_client import PrometheusClient

TICK_INTERVAL_SECONDS = 10


async def agent_loop() -> None:
    client = PrometheusClient()
    tick = 0
    while True:
        tick += 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{ts}] agent tick #{tick}")

        rates = client.request_rate()
        for row in rates:
            region = row["metric"].get("region", "?")
            tier = row["metric"].get("tier", "?")
            rps = row["value"][1]
            print(f"  {region}/{tier}: {rps} rps")

        await asyncio.sleep(TICK_INTERVAL_SECONDS)


def main() -> None:
    print("gdrl AI traffic agent starting — tick every 10s")
    asyncio.run(agent_loop())


if __name__ == "__main__":
    main()
