import json
import sys


def main() -> None:
    from ltp import LTP

    text = sys.stdin.read()[:100_000]
    model = LTP()
    output = model.pipeline([text], tasks=["cws", "pos", "ner", "srl", "dep"])
    value = output.to_dict() if hasattr(output, "to_dict") else {
        key: getattr(output, key, None) for key in ("cws", "pos", "ner", "srl", "dep")
    }
    print(json.dumps({"backend": "ltp", "available": True, "result": value}, ensure_ascii=False))


if __name__ == "__main__":
    main()
