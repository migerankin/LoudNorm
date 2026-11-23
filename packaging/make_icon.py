"""Generate packaging/autolevel.ico for the packaged executables."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from autolevel.iconart import write_ico  # noqa: E402

target = Path(__file__).resolve().parent / "autolevel.ico"
write_ico(target)
print(f"已生成 {target}（{target.stat().st_size} 字节）")
