#!/usr/bin/env python3
"""Interactive terminal prompt tool for AgenticTeam."""

from __future__ import annotations

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Halts agent and prompts the user for decisions.")
    parser.add_argument("--question", required=True, help="The question to ask the user")
    parser.add_argument("--options", help="Optional comma-separated selectable options")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    
    print("\n==================================================")
    print("📢 AGENT REQUESTS HUMAN CLARIFICATION / DECISION")
    print("==================================================")
    print(f"\nQuestion:\n  {args.question}")
    
    options_list = []
    if args.options:
        options_list = [opt.strip() for opt in args.options.split(",") if opt.strip()]
        print("\nOptions:")
        for idx, opt in enumerate(options_list, 1):
            print(f"  [{idx}] {opt}")
            
    print("\n==================================================")
    
    while True:
        try:
            if options_list:
                user_input = input(f"Please enter selection [1-{len(options_list)}] or write custom answer: ").strip()
            else:
                user_input = input("Please enter your answer: ").strip()
                
            if not user_input:
                print("Input cannot be empty. Please try again.")
                continue
                
            # If options are present, check if user selected a numeric option
            if options_list:
                try:
                    selection_idx = int(user_input)
                    if 1 <= selection_idx <= len(options_list):
                        selected_value = options_list[selection_idx - 1]
                        print(f"\n[Human Decision]: Selected Option {selection_idx} -> \"{selected_value}\"")
                        print(selected_value)
                        sys.exit(0)
                except ValueError:
                    # User typed a custom answer
                    pass
                    
            print(f"\n[Human Decision]: Custom Answer -> \"{user_input}\"")
            print(user_input)
            sys.exit(0)
            
        except (KeyboardInterrupt, EOFError):
            print("\nPrompt interrupted. Escalating to default.")
            sys.exit(1)


if __name__ == "__main__":
    main()
