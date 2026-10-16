"""The JS verifier's hash must agree with a reference implementation.

verify/blake2b.mjs is written out by hand so that the verifier needs nothing
installed. A hand-written hash is only trustworthy if something checks it, so
this compares it against Python's hashlib over every length that could expose
a padding or block-counter slip.
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node is not installed")

# Every length up to a block, the block boundaries themselves, and a spread
# beyond them. 0 and 128 are the two that hand-rolled padding gets wrong.
LENGTHS = sorted({*range(0, 130), 127, 128, 129, 255, 256, 257, 383, 384, 400})


def test_handwritten_blake2b_matches_hashlib(tmp_path):
    script = tmp_path / "run.mjs"
    script.write_text(
        f"import {{ blake2b256 }} from {json.dumps(str(ROOT / 'verify/blake2b.mjs'))};\n"
        f"const lengths = {json.dumps(LENGTHS)};\n"
        "const out = {};\n"
        "for (const n of lengths) {\n"
        "  const input = new Uint8Array(n);\n"
        "  for (let i = 0; i < n; i++) input[i] = (i * 37 + 11) & 0xff;\n"
        "  out[n] = [...blake2b256(input)]\n"
        "    .map((x) => x.toString(16).padStart(2, '0')).join('');\n"
        "}\n"
        "console.log(JSON.stringify(out));\n",
        encoding="utf-8")
    got = json.loads(subprocess.run(
        [node, str(script)], capture_output=True, text=True, check=True).stdout)

    assert len(got) == len(LENGTHS)
    for n in LENGTHS:
        data = bytes((i * 37 + 11) & 0xff for i in range(n))
        want = hashlib.blake2b(data, digest_size=32).hexdigest()
        assert got[str(n)] == want, f"length {n} disagrees"
