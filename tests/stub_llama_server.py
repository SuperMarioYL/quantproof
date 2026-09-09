#!/usr/bin/env python3
"""Deterministic llama-server stand-in for tests and the recorded demo.

Speaks just enough of the llama-server HTTP surface for quantproof:

* ``GET /health``              -> 200 {"status": "ok"}
* ``POST /v1/chat/completions`` -> a canned OpenAI-style chat completion

Responses come from a fixed answer table keyed by substrings of the user
prompt (targeting the bundled example pack), so the real grading code —
cc compile + diff for code tasks, substring checks for QA — runs for
real. This is a stub, not a model: pass rates recorded against it show
pipeline mechanics, never quant quality.

``--collapse-for`` (default: IQ1,IQ2,Q2,Q3) degrades a fixed subset of
answers whenever the ``-m`` model path contains one of the markers,
simulating a low-bits-per-weight collapse for the ranked table.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRIMES = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    int count = 0, n = 2;\n"
    "    while (count < 10) {\n"
    "        int prime = 1;\n"
    "        for (int d = 2; d * d <= n; d++) {\n"
    "            if (n % d == 0) { prime = 0; break; }\n"
    "        }\n"
    "        if (prime) { printf(\"%d\\n\", n); count++; }\n"
    "        n++;\n"
    "    }\n"
    "    return 0;\n"
    "}"
)

NUMBERS_1_10 = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    for (int i = 1; i <= 10; i++) printf(\"%d\\n\", i);\n"
    "    return 0;\n"
    "}"
)

FIZZBUZZ = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    for (int i = 1; i <= 15; i++) {\n"
    "        if (i % 15 == 0) printf(\"FizzBuzz\\n\");\n"
    "        else if (i % 3 == 0) printf(\"Fizz\\n\");\n"
    "        else if (i % 5 == 0) printf(\"Buzz\\n\");\n"
    "        else printf(\"%d\\n\", i);\n"
    "    }\n"
    "    return 0;\n"
    "}"
)

PLAIN_1_15 = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    for (int i = 1; i <= 15; i++) printf(\"%d\\n\", i);\n"
    "    return 0;\n"
    "}"
)

EVEN_SUM = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    int sum = 0;\n"
    "    for (int i = 2; i <= 100; i += 2) sum += i;\n"
    "    printf(\"%d\\n\", sum);\n"
    "    return 0;\n"
    "}"
)

ODD_SUM = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    int sum = 0;\n"
    "    for (int i = 1; i <= 100; i += 2) sum += i;\n"
    "    printf(\"%d\\n\", sum);\n"
    "    return 0;\n"
    "}"
)


def _fence(code: str) -> str:
    return f"```c\n{code}\n```"


# prompt substring (lowercase) -> (good answer, collapsed answer or None)
REVERSE = (
    "#include <stdio.h>\n"
    "#include <string.h>\n"
    "int main(void) {\n"
    "    char s[] = \"quantproof\";\n"
    "    for (int i = 0, j = (int)strlen(s) - 1; i < j; i++, j--) {\n"
    "        char t = s[i]; s[i] = s[j]; s[j] = t;\n"
    "    }\n"
    "    printf(\"%s\\n\", s);\n"
    "    return 0;\n"
    "}"
)

FIBONACCI = (
    "#include <stdio.h>\n"
    "int main(void) {\n"
    "    int a = 1, b = 1;\n"
    "    for (int i = 3; i <= 10; i++) { int t = a + b; a = b; b = t; }\n"
    "    printf(\"%d\\n\", b);\n"
    "    return 0;\n"
    "}"
)

ANSWERS: dict[str, tuple[str, str | None]] = {
    "prime": (_fence(PRIMES), _fence(NUMBERS_1_10)),
    "fizzbuzz": (_fence(FIZZBUZZ), _fence(PLAIN_1_15)),
    "even numbers": (_fence(EVEN_SUM), _fence(ODD_SUM)),
    "reversed": (_fence(REVERSE), None),
    "fibonacci": (_fence(FIBONACCI), None),
    "capital of france": ("Paris", "Lyon"),
    "closest to the sun": ("Mercury", None),
    "moon landing": ("1969", None),
    "volcano": ("Olympus Mons", None),
    "6.022": ("Avogadro", None),
}


def answer_for(prompt: str, model_path: str, markers: list[str], default: str) -> str:
    """Pick the canned answer for a prompt, degraded when the variant collapses."""
    collapsed = any(marker in model_path for marker in markers)
    lowered = prompt.lower()
    for key, (good, degraded) in ANSWERS.items():
        if key in lowered:
            if collapsed and degraded is not None:
                return degraded
            return good
    return default


class Handler(BaseHTTPRequestHandler):
    server_version = "quantproof-stub/0.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": {"message": f"not found: {self.path}"}})

    def do_POST(self) -> None:  # noqa: N802 — http.server API
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": f"not found: {self.path}"}})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "invalid JSON body"}})
            return
        if self.server.fail_completions:  # type: ignore[attr-defined]
            self._json(500, {"error": {"message": "stub failure requested"}})
            return
        prompt = _last_user_content(body)
        content = answer_for(
            prompt,
            self.server.model_path,  # type: ignore[attr-defined]
            self.server.collapse_markers,  # type: ignore[attr-defined]
            self.server.default_response,  # type: ignore[attr-defined]
        )
        self._json(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": "quantproof-stub",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, len(prompt) // 4),
                    "completion_tokens": max(1, len(content) // 4),
                    "total_tokens": max(1, len(prompt) // 4) + max(1, len(content) // 4),
                },
            },
        )

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _last_user_content(body: dict) -> str:
    for message in reversed(body.get("messages", [])):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else json.dumps(content)
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("-m", "--model", default="", help="model path (drives collapse mode)")
    parser.add_argument(
        "--collapse-for",
        default="IQ1,IQ2,Q2,Q3",
        help="comma-separated model-path markers that trigger degraded answers",
    )
    parser.add_argument("--default-response", default="OK", help="answer for unmatched prompts")
    parser.add_argument(
        "--fail-completions",
        action="store_true",
        help="answer every completion with HTTP 500",
    )
    args, _unknown = parser.parse_known_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.model_path = args.model  # type: ignore[attr-defined]
    server.collapse_markers = [m for m in args.collapse_for.split(",") if m]  # type: ignore[attr-defined]
    server.default_response = args.default_response  # type: ignore[attr-defined]
    server.fail_completions = args.fail_completions  # type: ignore[attr-defined]
    print(f"stub llama-server on :{args.port} (model={args.model})", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
