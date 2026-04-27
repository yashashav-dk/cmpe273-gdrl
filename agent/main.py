import asyncio
import time

TICK_INTERVAL_SECONDS = 10


async def agent_loop() -> None:
    tick = 0
    while True:
        tick += 1
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{ts}] agent tick #{tick}")
        await asyncio.sleep(TICK_INTERVAL_SECONDS)


def main() -> None:
    print("gdrl AI traffic agent starting — tick every 10s")
    asyncio.run(agent_loop())


if __name__ == "__main__":
    main()
