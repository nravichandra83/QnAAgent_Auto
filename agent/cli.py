"""Chat with the agent about one contract.

    python -m agent.cli CT-1001                       # interactive
    python -m agent.cli CT-1001 -q "What is the outstanding amount?"
    python -m agent.cli CT-1001 --as-of 2026-10-01 --show-sql --show-masked
"""
import argparse
import sys
from datetime import date

from agent.session import ContractNotFound, ContractSession


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract query agent")
    parser.add_argument("sequence_number", help="Contract sequence number, e.g. CT-1001")
    parser.add_argument("-q", "--question", help="Ask one question and exit")
    parser.add_argument("--as-of", type=date.fromisoformat, help="As-of date YYYY-MM-DD (default: today)")
    parser.add_argument("--show-sql", action="store_true", help="Print intent and SQL for each answer")
    parser.add_argument("--show-masked", action="store_true",
                        help="Print what the LLM saw (masked question and answer)")
    args = parser.parse_args()

    try:
        session = ContractSession(args.sequence_number)
    except ContractNotFound as err:
        print(err)
        sys.exit(1)

    def turn(question: str) -> None:
        result = session.ask(question, args.as_of)
        if args.show_masked:
            print(f"  [LLM saw question] {result.masked_question}\n  [LLM answered] {result.masked_answer}")
        if args.show_sql and result.state.get("sql"):
            print(f"  [intent: {result.state.get('intent')}]\n  [sql]\n{result.state['sql']}\n")
        print(result.answer)

    with session:
        if args.question:
            turn(args.question)
            return
        print(f"Contract {args.sequence_number}. Ask a question, or type 'exit'.")
        while True:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() in {"exit", "quit"}:
                break
            if question:
                turn(question)


if __name__ == "__main__":
    main()
