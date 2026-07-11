"""Phase 1 evaluation: orangebox (pure Python) vs blackbox_decode (C binary).

Runs both on the same sample logs, compares frame counts, values, and speed.
Run inside WSL: ~/.venvs/fpvbb/bin/python tools/eval_parsers.py
"""
import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
DECODE_BIN = ROOT / "vendor" / "blackbox-tools" / "obj" / "blackbox_decode"
SAMPLES = [DATA / "good_tune.BBL", DATA / "stock_tune.BFL"]


def eval_orangebox(path: Path):
    from orangebox import Parser

    out = {"backend": "orangebox", "file": path.name, "flights": []}
    t0 = time.perf_counter()
    parser = Parser.load(str(path))
    log_count = parser.reader.log_count
    for idx in range(1, log_count + 1):
        t1 = time.perf_counter()
        p = Parser.load(str(path), idx)
        names = p.field_names
        frames = []
        err = None
        try:
            for fr in p.frames():
                frames.append(fr.data)
        except Exception as e:  # corrupt tail etc.
            err = f"{type(e).__name__}: {e}"
        dt = time.perf_counter() - t1
        ti = names.index("time")
        dur = (frames[-1][ti] - frames[0][ti]) / 1e6 if frames else 0.0
        out["flights"].append({
            "index": idx,
            "n_fields": len(names),
            "n_frames": len(frames),
            "duration_s": round(dur, 2),
            "parse_s": round(dt, 2),
            "error": err,
            "n_headers": len(p.headers),
            "field_names": names,
            "first_frames": frames[:3],
            "frames": frames,
        })
    out["total_s"] = round(time.perf_counter() - t0, 2)
    return out


def eval_blackbox_decode(path: Path):
    out = {"backend": "blackbox_decode", "file": path.name, "flights": []}
    workdir = ROOT / "tools" / "_decode_out"
    workdir.mkdir(exist_ok=True)
    tmp = workdir / path.name
    tmp.write_bytes(path.read_bytes())
    t0 = time.perf_counter()
    r = subprocess.run(
        [str(DECODE_BIN), "--stdout" if False else str(tmp)],
        capture_output=True, text=True, timeout=300,
    )
    total = time.perf_counter() - t0
    # blackbox_decode writes <name>.<index>.csv next to the input
    for csv_path in sorted(workdir.glob(tmp.stem + ".*.csv")):
        if "gps" in csv_path.name.lower():
            continue
        with open(csv_path, newline="") as fh:
            reader = csv.reader(fh)
            header = [h.strip() for h in next(reader)]
            rows = list(reader)
        ti = header.index("time (us)")
        dur = (float(rows[-1][ti]) - float(rows[0][ti])) / 1e6 if rows else 0.0
        out["flights"].append({
            "csv": csv_path.name,
            "n_fields": len(header),
            "n_frames": len(rows),
            "duration_s": round(dur, 2),
            "field_names": header,
            "rows": rows,
        })
    out["total_s"] = round(total, 2)
    out["stderr_tail"] = r.stderr.strip().splitlines()[-4:]
    return out


def compare(ob, bd):
    """Value-level reconciliation between backends for each flight."""
    print(f"\n=== {ob['file']} ===")
    print(f"orangebox: {len(ob['flights'])} flight(s) in {ob['total_s']}s | "
          f"blackbox_decode: {len(bd['flights'])} flight(s) in {bd['total_s']}s")
    for f_ob, f_bd in zip(ob["flights"], bd["flights"]):
        print(f"\n  flight {f_ob['index']}: frames ob={f_ob['n_frames']} bd={f_bd['n_frames']} "
              f"| duration ob={f_ob['duration_s']}s bd={f_bd['duration_s']}s "
              f"| parse ob={f_ob['parse_s']}s | headers={f_ob['n_headers']}"
              + (f" | OB-ERROR: {f_ob['error']}" if f_ob["error"] else ""))
        # value agreement on shared numeric columns, aligned by loopIteration
        ob_names, bd_names = f_ob["field_names"], f_bd["field_names"]
        bd_map = {}
        for j, n in enumerate(bd_names):
            key = n.replace(" (us)", "").strip()
            bd_map[key] = j
        shared = [n for n in ob_names if n in bd_map]
        ob_li = ob_names.index("loopIteration")
        bd_li = bd_map["loopIteration"]
        ob_by_li = {fr[ob_li]: fr for fr in f_ob["frames"]}
        n_aligned = mismatched = 0
        bad_cols = {}
        for row in f_bd["rows"][:200000]:
            li = int(row[bd_li])
            fr = ob_by_li.get(li)
            if fr is None:
                continue
            n_aligned += 1
            for name in shared:
                a = fr[ob_names.index(name)]
                try:
                    b = float(row[bd_map[name]])
                    a = float(a)
                except (ValueError, TypeError):
                    continue
                if abs(a - b) > 1e-6:
                    mismatched += 1
                    bad_cols.setdefault(name, 0)
                    bad_cols[name] += 1
        print(f"    shared columns: {len(shared)} | aligned frames: {n_aligned} "
              f"| cell mismatches: {mismatched}")
        if bad_cols:
            top = sorted(bad_cols.items(), key=lambda kv: -kv[1])[:8]
            print(f"    mismatching columns: {top}")
        # debug: raw time field span to explain any duration mismatch
        ob_t = ob_names.index("time")
        times = [fr[ob_t] for fr in f_ob["frames"]]
        dt = [times[i+1]-times[i] for i in range(len(times)-1)]
        biggest = sorted(dt, reverse=True)[:5]
        print(f"    orangebox time span: first={times[0]} last={times[-1]} "
              f"biggest inter-frame gaps (us): {biggest}")


if __name__ == "__main__":
    for sample in SAMPLES:
        ob = eval_orangebox(sample)
        bd = eval_blackbox_decode(sample)
        compare(ob, bd)
    print("\nField names (orangebox, first flight of first file) for reference:")
