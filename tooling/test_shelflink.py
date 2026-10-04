"""Run the shelflink unit tests on the SDCC simulator (s51).

  sl_proto_test.c   frame build/parse and the duplicate filter (sl_proto.c)
  shelflink_test.c  the retry / acknowledge state machine (shelflink.c) against stubs
                    for the radio engine, the wake-up timers and the random source

Each test is compiled for the AX8052 memory model, run until done() and its
per-check results are read back from the simulator.

    python tooling/test_shelflink.py

Needs SDCC (sdcc, s51) on PATH or in C:\\Program Files\\SDCC\\bin.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "shared" / "firmware"
LINK = FW / "shelflink"
TESTS_DIR = Path(__file__).resolve().parent / "tests"
FLAGS = ["-mmcs51", "--model-small", "--iram-size", "256", "--xram-size", "8192",
         f"-I{ROOT / 'shared' / 'sdk' / 'libmf' / 'include'}",
         f"-I{LINK / 'inc'}", f"-I{LINK}", f"-I{FW / 'shelfhw' / 'inc'}", f"-I{FW / 'axradio' / 'inc'}"]
TESTS = {
    "proto": [TESTS_DIR / "sl_proto_test.c", LINK / "sl_proto.c"],
    "link": [TESTS_DIR / "shelflink_test.c", LINK / "shelflink.c", LINK / "sl_proto.c"],
}


def tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    fallback = Path(r"C:\Program Files\SDCC\bin") / f"{name}.exe"
    if fallback.exists():
        return str(fallback)
    sys.exit(f"{name} not found - install SDCC or add it to PATH")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def run_test(name: str, sources: list[Path]) -> bool:
    sdcc, s51 = tool("sdcc"), tool("s51")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        rels = []
        for i, src in enumerate(sources):
            rel = tmp / f"{i}_{src.stem}.rel"
            p = run([sdcc, "-c", *FLAGS, str(src), "-o", str(rel)])
            if p.returncode:
                print(f"{name}: compile of {src.name} failed\n{p.stderr or p.stdout}")
                return False
            rels.append(str(rel))
        p = run([sdcc, *FLAGS, *rels, "-o", str(tmp / "test.ihx")])
        if p.returncode:
            print(f"{name}: link failed\n{p.stderr or p.stdout}")
            return False

        sym = {m.group(2): int(m.group(1), 16)
               for m in re.finditer(r"^\s*[A-Z]:\s+([0-9A-Fa-f]{8})\s+(_\w+)",
                                    (tmp / "test.map").read_text(), re.M)}
        results, nfail, done = sym["_results"], sym["_nfail"], sym["_done"]

        script = tmp / "cmds.txt"
        script.write_text(f"run 0 0x{done:x}\ndx 0x{results:x} 0x{nfail:x}\nquit\n")
        try:
            p = subprocess.run([s51, "-t", "51", "-P", str(tmp / "test.ihx")],
                               stdin=script.open(), capture_output=True, timeout=30)
            out = p.stdout
        except subprocess.TimeoutExpired as e:
            out = e.stdout or b""        # s51 keeps prompting after quit; the dump is already there
        text = out.decode("latin-1").replace("\x00", "\n")

    values = []
    for line in text.splitlines():
        m = re.match(r"^0x[0-9a-f]{4}((?: [0-9a-f]{2}){1,8})", line)
        if m:
            values += [int(b, 16) for b in m.group(1).split()]
    if "Stop at" not in text or not values:
        print(f"{name}: simulator did not reach done()\n{text[-800:]}")
        return False
    ran = [v for v in values[: nfail - results] if v in (1, 0xEE)]
    bad = [i for i, v in enumerate(ran) if v != 1]
    print(f"{name}: {len(ran) - len(bad)}/{len(ran)} checks passed" + (f", failed (0-based): {bad}" if bad else ""))
    return not bad


def main() -> int:
    ok = [run_test(name, sources) for name, sources in TESTS.items()]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
