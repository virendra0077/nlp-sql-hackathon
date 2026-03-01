from sql_agent import execute_with_retry
from db import close_pool


def format_result(result: list[tuple]) -> str:
    if not result:
        return "(no rows returned)"
    if len(result) == 1 and len(result[0]) == 1:
        # Single scalar — format with commas if numeric
        val = result[0][0]
        try:
            return f"{float(val):,.2f}"
        except (TypeError, ValueError):
            return str(val)

    # Multi-row: simple table
    lines = []
    for row in result:
        lines.append("  |  ".join(str(c) for c in row))
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("  Real Estate SQL Agent  (type 'exit' to quit)")
    print("=" * 60)

    try:
        while True:
            question = input("\nAsk a question: ").strip()
            if not question:
                continue
            if question.lower() in ("exit", "quit", "q"):
                break

            try:
                sql, result = execute_with_retry(question)
                print("\n[Result]")
                print(format_result(result))

            except RuntimeError as e:
                print(f"\n[Error] {e}")

    except KeyboardInterrupt:
        print("\nInterrupted.")

    finally:
        close_pool()
        print("Goodbye.")


if __name__ == "__main__":
    main()