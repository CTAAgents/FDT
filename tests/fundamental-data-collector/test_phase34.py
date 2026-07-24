"""Phase 3.3+3.4 快速验证。"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "fundamental-data-collector"))

from scripts.structured_data import apply_fundamental_cleaning, align_to_timeline

# Test apply_fundamental_cleaning
data, summary = apply_fundamental_cleaning(
    {"开工率": "36.5%", "_source": "test"},
    "inventory",
    symbol="RB"
)
print(f"apply_fundamental_cleaning(RB): OK (summary={summary})")

# Test align_to_timeline
result = align_to_timeline(
    {"_updated": "2026-07-04", "利润": "80元/吨"},
    target_dates=["20260701", "20260702", "20260703"],
    method="ffill"
)
assert "_timeline" in result
assert result["_timeline"]["method"] == "ffill"
assert result["_timeline"]["target_count"] == 3
print(f"align_to_timeline: OK (aligned={result['_timeline']['aligned']})")

# Test apply_fundamental_cleaning with SA (caliber detection)
data2, summary2 = apply_fundamental_cleaning(
    {"_source": "test"},
    "basis",
    symbol="SA"
)
print(f"apply_fundamental_cleaning(SA): OK")

# Test align_to_timeline with empty data
result2 = align_to_timeline(
    {"info": "无数据"},
    method="interp"
)
assert "_timeline" in result2
print(f"align_to_timeline(empty): OK")

print("\nAll assertions PASSED")
