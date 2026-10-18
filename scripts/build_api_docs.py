"""生成并校验中文 API 文档；只读接口定义，不启动服务或访问业务数据库。"""
import argparse
import ast
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}
PUBLIC = {'GET /api/health', 'GET /api/v1/auth/csrf', 'POST /api/v1/auth/login'}
PARAMETERS = {
    'page': '页码，从 1 开始；是否省略会影响部分列表的响应格式，详见返回说明。',
    'page_size': '每页数量，默认 10，最大 100。',
    'offset': '兼容旧调用的起始偏移，从 0 开始；指定 page 时由页码计算。',
    'limit': '兼容旧调用的返回数量；指定 page 时使用 page_size。',
    'q': '搜索关键词；搜索范围见本接口说明。',
    'deleted': '是否查询已删除记录；true 仅管理员可用。',
    'group_id': '来源聊天容器 UUID；通常从导入记录或消息取得。',
    'customer_id': '数据权限范围 UUID；筛选仍受当前账号权限限制。',
    'import_id': '导入文件记录 UUID，即 batch.id。',
    'batch_id': '导入文件记录 UUID，用于仅查询该文件的消息或任务。',
    'issue_id': '问题 UUID，从问题列表或消息的 assigned_issues 取得。',
    'message_id': '聊天消息 UUID，从消息列表或导入预览取得。',
    'object_id': '工单或 QA 主记录 UUID；不是修订版本 UUID。',
    'revision_id': '目标修订版本 UUID，从记录详情的 revisions 取得。',
    'ticket_id': '工单主记录 UUID，从工单列表或问题详情取得。',
    'job_id': '生成任务 UUID，从创建任务响应或任务列表取得。',
    'user_id': '内部账号 UUID，从账号列表取得。',
    'role': '账号角色：admin 管理员、agent 客服、reviewer 审核员。',
    'screening': '预筛选范围：all 全部、filtered 仍被过滤、retained 保留（含已恢复）。',
    'dry_run': 'true 仅预览重判；false 应用重判。即使仅预览仍是受保护的 POST 请求。',
    'state': '消息处置状态；本接口支持的值及含义见接口说明。',
    'status': '记录状态筛选；可用值见枚举及接口说明。',
    'record_kind': '可恢复记录类型：message、import、ticket、qa、ticket_draft、qa_draft。',
    'record_id': '对应类型的记录 UUID；删除草稿时传修订版本 UUID。',
    'action': '操作名称；审核为 submit/approve/reject，任务为 cancel/retry。',
}


def read_json(name):
    return json.loads((DOCS / name).read_text(encoding='utf-8'))


def operations(schema):
    return {f'{method.upper()} {path}': operation
            for path, item in schema['paths'].items()
            for method, operation in item.items() if method in METHODS}


def validate_source_routes(schema):
    """防止新增/删改路由后仍发布过期接口清单。"""
    tree = ast.parse((ROOT / 'backend/app/main.py').read_text(encoding='utf-8-sig'))
    paths = set()

    def path_value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id == 'PREFIX':
            return '/api/v1'
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return path_value(node.left) + path_value(node.right)
        raise ValueError('无法静态解析路由，请刷新检查器')

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == 'app' and decorator.func.attr in METHODS):
                paths.add(f'{decorator.func.attr.upper()} {path_value(decorator.args[0])}')
    if paths != set(operations(schema)):
        raise ValueError(f'OpenAPI 快照与源码路由不一致：缺少 {paths-set(operations(schema))}；多余 {set(operations(schema))-paths}')


def chinese(text):
    return isinstance(text, str) and bool(re.search(r'[\u3400-\u9fff]', text))


def validate_notes(schema, routes, models):
    actual = operations(schema)
    if set(actual) != set(routes):
        raise ValueError(f'接口注释覆盖不完整：{set(actual)^set(routes)}')
    for key, note in routes.items():
        for field in ('summary', 'tag', 'description', 'access', 'version', 'response'):
            if not chinese(note.get(field)):
                raise ValueError(f'{key} 缺少中文 {field}')
        for parameter in actual[key].get('parameters', []):
            description = note.get('parameters', {}).get(parameter['name'], PARAMETERS.get(parameter['name']))
            if not chinese(description):
                raise ValueError(f'{key} 参数 {parameter["name"]} 缺少中文说明')
    schemas = schema['components']['schemas']
    if set(models) != set(schemas):
        raise ValueError(f'模型注释覆盖不完整：{set(models)^set(schemas)}')
    for name, value in schemas.items():
        note = models[name]
        if not chinese(note.get('description')):
            raise ValueError(f'{name} 缺少中文说明')
        if set(note.get('properties', {})) != set(value.get('properties', {})):
            raise ValueError(f'{name} 字段注释与模型不一致')
        if not all(chinese(v) for v in note.get('properties', {}).values()):
            raise ValueError(f'{name} 有字段缺少中文说明')


def annotate(schema, routes, models):
    result = copy.deepcopy(schema)
    result['info']['title'] = '知序客户服务记录 API 中文说明'
    result['info']['description'] = (
        '按当前实现补充的中文接口契约。使用 Cookie 会话、CSRF 和 Origin 校验；'
        '写请求通常还需要 Idempotency-Key，指定接口需要 If-Match。'
        '完整流程、中文代码注释和响应说明见 docs/api-guide.zh-CN.md 与 docs/api-reference.zh-CN.md。'
        '本文件供接口工具导入，不改变线上 /api/openapi.json；未声明的成功响应 schema 仍保持开放，不能据此生成完整响应类型。'
    )
    result['tags'] = [{'name': tag} for tag in dict.fromkeys(note['tag'] for note in routes.values())]
    result['components'].setdefault('securitySchemes', {})['SessionCookie'] = {
        'type': 'apiKey', 'in': 'cookie', 'name': 'sr_session',
        'description': '通过 /api/v1/auth/login 登录后由服务端设置的 HttpOnly 会话 Cookie；不是 Bearer Token。',
    }
    for key, operation in operations(result).items():
        note = routes[key]
        operation['summary'] = note['summary']
        operation['tags'] = [note['tag']]
        operation['description'] = '\n\n'.join([
            note['description'], '权限：' + note['access'], '版本校验：' + note['version'],
            '响应说明：' + note['response'], *note.get('notes', []),
        ])
        operation['security'] = [] if key in PUBLIC else [{'SessionCookie': []}]
        for parameter in operation.get('parameters', []):
            parameter['description'] = note.get('parameters', {}).get(parameter['name'], PARAMETERS.get(parameter['name']))
        if key.split()[0] not in ('GET', 'HEAD', 'OPTIONS'):
            headers = [
                ('Origin', True, '浏览器自动发送；脚本需填写 APP_ORIGINS 中允许的完整前端来源（协议、主机、端口），不含路径。'),
                ('X-CSRF-Token', True, '从 /auth/csrf 或登录响应 JSON 读取；登录成功后更新为新的 csrf_token，并携带服务端 Cookie。'),
            ]
            if key != 'POST /api/v1/auth/logout':
                headers.append(('Idempotency-Key', key != 'POST /api/v1/auth/login',
                                '同一次写操作重试复用相同键与请求体；不同操作使用新键。未登录时登录可省略；已有有效会话时登录也需要。长度 1 至 128。'))
            if note['version'] != '无':
                headers.append(('If-Match', True, note['version'] + '；格式必须包含双引号，例如 "3"。'))
            operation.setdefault('parameters', []).extend(
                {'name': name, 'in': 'header', 'required': required, 'schema': {'type': 'string'}, 'description': description}
                for name, required, description in headers
            )
        if 'requestBody' in operation:
            operation['requestBody']['description'] = '请求内容及字段含义见对应 schema；JSON 字段名必须保持英文。'
        for status, response in operation.get('responses', {}).items():
            response['description'] = note['response'] if status.startswith('2') else (
                '请求参数或业务校验未通过；框架参数错误的 detail 为数组，业务错误的 detail 为含 code、message 的对象。'
                if status == '422' else '请求失败，参见中文接入指南的错误处理。'
            )
    for name, value in result['components']['schemas'].items():
        value['description'] = models[name]['description']
        for field, definition in value.get('properties', {}).items():
            definition['description'] = models[name]['properties'][field]
    return result


def type_text(value):
    if '$ref' in value:
        name = value['$ref'].rsplit('/', 1)[-1]
        return f'[{name}](#{name.lower()})'
    if 'anyOf' in value:
        return ' 或 '.join(type_text(v) for v in value['anyOf'])
    if value.get('type') == 'array':
        return '数组〈' + type_text(value.get('items', {})) + '〉'
    base = {'string': '字符串', 'integer': '整数', 'number': '数值', 'boolean': '布尔值', 'null': 'null', 'object': '对象'}.get(value.get('type'), '开放结构')
    if value.get('format'):
        base += f'（{value["format"]}）'
    return base


def constraints(value):
    parts = []
    for option in value.get('anyOf', []):
        item = constraints(option)
        if item:
            parts.append(item)
    for key, label in [('minimum','最小值'), ('maximum','最大值'), ('minLength','最短字符数'), ('maxLength','最长字符数'), ('minItems','最少项数'), ('maxItems','最多项数')]:
        if key in value:
            parts.append(f'{label} {value[key]}')
    if 'enum' in value:
        parts.append('可选 ' + '、'.join('`' + str(v) + '`' for v in value['enum']))
    if 'default' in value:
        parts.append('默认 `' + json.dumps(value['default'], ensure_ascii=False) + '`')
    if 'pattern' in value:
        parts.append('格式 `' + value['pattern'] + '`')
    return '；'.join(parts)


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |',
            *['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows], '']


def render(schema, routes, models):
    ops = operations(schema)
    out = ['# 知序系统 API 中文接口参考', '',
           '适用于当前 FastAPI 实现，共 ' + str(len(ops)) + ' 个 HTTP 操作。接入前请先阅读 [中文接入指南](api-guide.zh-CN.md)，其中包含登录、请求头、版本校验、错误处理和带中文注释的调用示例。', '',
           '本参考由 `scripts/build_api_docs.py` 根据现有 OpenAPI 与中文注释生成。接口路径、方法、字段类型和约束沿用原契约；权限、版本号和返回结构说明补充自实现。成功响应未定义完整 schema 的接口，下面列出主要字段，不代表穷尽全部返回字段。', '',
           '## 接口目录', '']
    out += table(['模块', '方法与路径', '用途'], [(routes[k]['tag'], f'`{k}`', routes[k]['summary']) for k in ops])
    group = None
    for index, (key, operation) in enumerate(ops.items(), 1):
        note = routes[key]
        if group != note['tag']:
            group = note['tag']
            out += [f'## {index:02d} {group}', '']
        out += [f'### {index:02d} {note["summary"]}', '', '`' + key + '`', '', note['description'], '',
                '- 权限：' + note['access'], '- If-Match：' + note['version'], '']
        params = operation.get('parameters', [])
        if params:
            out += table(['参数', '位置', '必填', '类型与约束', '中文说明'], [
                (f'`{p["name"]}`', {'path':'路径','query':'查询','header':'请求头'}.get(p['in'],p['in']), '是' if p.get('required') else '否',
                 type_text(p.get('schema',{})) + ('；' + constraints(p['schema']) if constraints(p.get('schema',{})) else ''),
                 note.get('parameters',{}).get(p['name'],PARAMETERS.get(p['name'],''))) for p in params
            ])
        if 'requestBody' in operation:
            body = operation['requestBody']
            for media, definition in body.get('content', {}).items():
                body_schema = definition.get('schema', {})
                out += [f'请求体：`{media}`，' + ('必填' if body.get('required') else '可选') + '；' + type_text(body_schema) + '。', '']
        else:
            out += ['请求体：无。', '']
        success_codes = [s for s in operation['responses'] if s.startswith('2')]
        status_line = '成功状态：' + '、'.join('`' + s + '`' for s in success_codes) + '。'
        out += [status_line, '', note['response'], '']
        out += ['- ' + text for text in note.get('notes', [])]
        out += ['']
    out += ['## 请求与校验模型', '', '标为“必填”的属性必须提交；“可选”只表示可省略，只有类型包含 null 时才允许显式传 null。业务请求模型默认拒绝未声明的额外字段。JSON 不支持注释，中文说明放在表格和 OpenAPI 的 description 中。', '']
    for name, value in schema['components']['schemas'].items():
        out += ['### ' + name, '', models[name]['description'], '']
        required = value.get('required', [])
        out += table(['字段', '必填', '类型', '约束和默认值', '中文说明'], [
            (f'`{field}`', '是' if field in required else '否', type_text(definition), constraints(definition) or '—', models[name]['properties'][field])
            for field, definition in value.get('properties', {}).items()
        ])
    return '\n'.join(out).rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只检查输出是否最新，不改文件')
    args = parser.parse_args()
    schema = read_json('openapi-v1.json')
    routes = read_json('api-route-notes.zh-CN.json')
    models = read_json('api-schema-notes.zh-CN.json')
    validate_source_routes(schema)
    validate_notes(schema, routes, models)
    outputs = {
        'openapi-v1.zh-CN.json': json.dumps(annotate(schema, routes, models), ensure_ascii=False, indent=2) + '\n',
        'api-reference.zh-CN.md': render(schema, routes, models),
    }
    for filename, content in outputs.items():
        path = DOCS / filename
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit(f'文档未同步：{filename}；请运行 python scripts/build_api_docs.py')
        else:
            path.write_text(content, encoding='utf-8', newline='\n')
    print(f'中文 API 文档校验通过：{len(operations(schema))} 个操作，{len(models)} 个模型。')


if __name__ == '__main__':
    main()
