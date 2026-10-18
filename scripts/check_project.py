"""检查源码、接口文档、文档链接和 Dify 生成文件是否同步；不访问业务库。"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for args in [
        ['scripts/export_openapi.py', '--check'],
        ['scripts/build_api_docs.py', '--check'],
        ['-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_dify_prompts.py'],
    ]:
        subprocess.run([sys.executable, *args], cwd=ROOT, check=True)
    for path in [ROOT / 'README.md', *sorted((ROOT / 'docs').glob('*.md'))]:
        text = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if link.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            target = (path.parent / link.split('#', 1)[0]).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                raise SystemExit(f'文档链接失效：{path.relative_to(ROOT)} -> {link}')
    print('项目一致性检查通过：接口契约、中文说明、Dify 产物和文档链接均已同步。')


if __name__ == '__main__':
    main()
