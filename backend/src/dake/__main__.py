"""允许 python -m dake 调用同一个命令入口。"""

from .cli import main

raise SystemExit(main())
