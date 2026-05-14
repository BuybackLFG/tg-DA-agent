import sys
import os
import json

def main():
    if len(sys.argv) < 2:
        print("Usage: run.py <script_path>", file=sys.stderr)
        sys.exit(1)

    script_path = sys.argv[1]

    if not os.path.exists(script_path):
        print(f"Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    # Execute the script in a restricted namespace
    exec(open(script_path).read(), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
