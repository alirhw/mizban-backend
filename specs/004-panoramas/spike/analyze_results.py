"""Analysis script for Spike T-019 results.json."""
import json
import os
import statistics
from collections import defaultdict

results_file = os.path.join(os.path.dirname(__file__), "results.json")
with open(results_file, encoding="utf-8") as f:
    data = json.load(f)

groups = defaultdict(list)
for r in data:
    f_short = r["fixture"].split("/")[-1]
    p = r["profile"]
    groups[(p, f_short)].append(r)

print(f"Total trials collected: {len(data)}")
print("\nAGGREGATE RESULTS MATRIX:")
header = f"{'Profile':<22} | {'Fixture':<30} | {'Size MB':<8} | {'Avg FPS':<8} | {'1% Low':<8} | {'Min FPS':<8} | {'1st Paint':<10} | {'Load ms':<10} | {'Heap MB':<8} | {'Dropped%':<9}"
print(header)
print("-" * len(header))

for (p, f_short), trials in groups.items():
    size_mb = trials[0]["fixture_size_bytes"] / (1024 * 1024)
    avg_fps = statistics.mean([t["avg_fps"] for t in trials])
    low_fps = statistics.mean([t["one_percent_low_fps"] for t in trials])
    min_fps = statistics.mean([t["min_fps"] for t in trials])
    paint_ms = statistics.mean([t["t_first_paint_ms"] for t in trials])
    load_ms = statistics.mean([t["t_load_ms"] for t in trials])
    heap_mb = statistics.mean([t["js_heap_mb"] for t in trials if t["js_heap_mb"] is not None])
    drop_pct = statistics.mean([t["dropped_frames_30_pct"] for t in trials])
    print(
        f"{p:<22} | {f_short:<30} | {size_mb:>7.2f}M | {avg_fps:>7.1f}  | {low_fps:>7.1f}  | {min_fps:>7.1f}  | {paint_ms:>8.1f}ms | {load_ms:>8.1f}ms | {heap_mb:>6.2f}MB | {drop_pct:>7.2f}%"
    )
