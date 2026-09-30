"""
Self-test for the free SMS scrapers — run WITHOUT Telegram:

    python test_scrapers.py

It lists countries/numbers from each free source and tries to read the
inbox of the first number, so you can verify the scrapers still work
after the websites change their layout.
"""

import asyncio
import sys

from scrapers import SOURCES, SmsMessage, SourceError, pretty_number


async def test_source(idx: int, src) -> None:
    print(f"\n{'='*60}\n[{idx}] {src.name}  ({src.home})")
    try:
        countries = await src.list_countries()
    except SourceError as e:
        print(f"  ❌ countries failed: {e}")
        return
    print(f"  ✅ countries: {len(countries)}  -> {list(countries.items())[:6]}")

    if not countries:
        print("  ⚠️ no countries found")
        return

    numbers = []
    name = key = None
    for name, key in list(countries.items())[:5]:
        try:
            numbers = await src.list_numbers(key)
        except SourceError as e:
            print(f"  ❌ numbers failed: {e}")
            return
        if numbers:
            break
    if not numbers:
        print(f"  ⚠️ no numbers in first 5 countries (last tried: {name})")
        return
    print(f"  ✅ {name}: {len(numbers)} numbers -> {[pretty_number(n) for n in numbers[:5]]}")

    if not numbers:
        return
    try:
        msgs = await src.get_messages(numbers[0], key)
    except SourceError as e:
        print(f"  ❌ messages failed: {e}")
        return
    print(f"  ✅ inbox of {pretty_number(numbers[0])}: {len(msgs)} messages")
    for m in msgs[:3]:
        print(f"     • {m.sender or '?'} | {m.time or '?'} | {m.text[:70]!r}")


async def main() -> None:
    print("Testing free SMS sources…")
    for i, src in enumerate(SOURCES):
        try:
            await test_source(i, src)
        except Exception as e:
            print(f"  ❌ unexpected error: {e!r}")
    from scrapers import close_all
    await close_all()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
