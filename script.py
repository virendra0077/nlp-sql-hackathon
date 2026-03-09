"""
cli.py - Ask natural language questions about your real estate data from the terminal.

Usage:
    python cli.py
    python cli.py "What are the total sales in Prabadevi Address?"
"""

import sys
import time
from dotenv import load_dotenv

load_dotenv()

from sql_agent import execute_with_retry


def format_result(result: list) -> str:
    if not result:
        return "No data found."

    if len(result) == 1 and len(result[0]) == 1:
        val = result[0][0]
        if val is None:
            return "No matching data found. Check the asset name exists in the database."
        try:
            num = float(val)
            abs_num = abs(num)
            sign = "-" if num < 0 else ""
            if abs_num >= 10_000_000:
                return f"{sign}Rs {abs_num / 10_000_000:,.2f} Cr"
            elif abs_num >= 100_000:
                return f"{sign}Rs {abs_num / 100_000:,.2f} L"
            elif abs_num == int(abs_num):
                return f"{sign}{int(abs_num):,}"
            else:
                return f"{sign}{abs_num:,.2f}"
        except (TypeError, ValueError):
            return str(val)

    rows = []
    for row in result:
        parts = []
        for cell in row:
            if cell is None:
                parts.append("—")
            else:
                try:
                    num = float(cell)
                    if abs(num) >= 10_000_000:
                        parts.append(f"Rs {num / 10_000_000:,.2f} Cr")
                    else:
                        parts.append(str(cell))
                except (TypeError, ValueError):
                    parts.append(str(cell))
        rows.append("  |  ".join(parts))
    return "\n".join(rows)


def ask(question: str):
    print(f"\n{'─' * 60}")
    print(f"  Question : {question}")
    print(f"{'─' * 60}")
    print("  Thinking...\n")

    start = time.time()
    try:
        sql, result = execute_with_retry(question)
        duration_ms = int((time.time() - start) * 1000)

        print(f"  SQL      :\n")
        for line in sql.strip().splitlines():
            print(f"    {line}")

        print(f"\n  Answer   : {format_result(result)}")
        print(f"  Duration : {duration_ms} ms")
        print(f"{'─' * 60}\n")

    except RuntimeError as e:
        print(f"  ERROR    : {e}")
        print(f"{'─' * 60}\n")


def interactive_loop():
    print("\n╔══════════════════════════════════════════════╗")
    print("║      Real Estate SQL Agent — Terminal CLI    ║")
    print("╚══════════════════════════════════════════════╝")
    print("  Type your question and press Enter.")
    print("  Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            question = input("  You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Goodbye!\n")
            break

        if not question:
            continue

        if question.lower() in ("exit", "quit", "q"):
            print("\n  Goodbye!\n")
            break

        ask(question)


if __name__ == "__main__":
    # If a question is passed as a command-line argument, answer it and exit
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        ask(question)
    else:
        # Otherwise start the interactive loop
        interactive_loop()