import json
import sys

from . import compile_to_code


def main():
    definition = sys.argv[1] if len(sys.argv) == 2 else sys.stdin.read()
    definition = json.loads(definition)
    code = compile_to_code(definition)
    print(code)


if __name__ == '__main__':
    main()
