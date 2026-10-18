"""从当前 FastAPI 路由导出接口契约；不启动服务、不连接数据库。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只检查契约与源码是否一致')
    args = parser.parse_args()
    from app.main import app
    current = app.openapi()
    path = ROOT / 'docs/openapi-v1.json'
    if args.check:
        if not path.exists() or json.loads(path.read_text(encoding='utf-8')) != current:
            raise SystemExit('接口快照已过时：请运行 python scripts/export_openapi.py，然后重新生成中文文档。')
    else:
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('OpenAPI 与当前 FastAPI 路由、参数和模型一致。')


if __name__ == '__main__':
    main()
