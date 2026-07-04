#!python
# encoding: utf-8

import json
import time
import os
import sys
import click
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import logging

from rich.console import Console
from rich.table import Table

# ------------------------------------------------------------------------------------------
# global variables
_CONSOLE = Console()

# TODO: difoss_stock_util.click_util 会导致程序启动变慢，需要优化
# from difoss_stock_util.click_util import split_comma


def split_comma(ctx: click.Context, param: click.Parameter, value) -> list[str]:
    """将逗号分隔的字符串拆分为列表，同时支持多个值"""
    if not value:
        return []

    result = set()

    if isinstance(value, str):
        value = [value] if value else []

    for v in value:
        # 如果值中包含逗号，进一步分割
        if isinstance(v, str) and ',' in v:
            result.update([v.strip() for v in v.split(',') if v.strip()])
        else:
            result.add(v)

    return list(result)


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def escape_path_for_claude(path: str) -> str:
    """
    将文件系统路径转义为 Claude 项目目录名。

    规则：
    - :, \\, _ 都替换为 -

    示例：Z:\\stock_\\miniQMT.code → Z--stock_-miniQMT.code
    """
    for char in [':', '\\', '_', '.']:
        path = path.replace(char, '-')
    return path


def get_project_dir() -> Optional[Path]:
    """
    获取当前工作目录对应的 Claude transcript 项目目录：
    $HOME/.claude/projects/{转义后的当前目录}
    """
    home = Path.home()
    cwd = os.getcwd()
    escaped = escape_path_for_claude(cwd)
    project_dir = home / '.claude' / 'projects' / escaped
    return project_dir if project_dir.is_dir() else None


def get_default_jsonl_file() -> Optional[Path]:
    """
    获取默认的 JSONL 文件：项目目录下修改时间最新的 .jsonl 文件。
    如果目录不存在或无 jsonl 文件，返回 None。
    """
    project_dir = get_project_dir()
    if project_dir is None:
        logger.info("默认项目目录不存在")
        return None

    jsonl_files = list(project_dir.glob('*.jsonl'))
    if not jsonl_files:
        logger.info(f"目录下没有 .jsonl 文件: {project_dir}")
        return None

    # 按修改时间降序，取最新的
    latest = max(jsonl_files, key=lambda f: f.stat().st_mtime)
    logger.info(f"自动选择最新 JSONL 文件: {latest}")
    return latest


def list_file_types(filepath: Path) -> dict:
    """
    扫描 jsonl 文件，统计所有 'type' 值的出现次数。
    """
    type_counts: dict[str, int] = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                t = data.get('type', '(无 type 字段)')
                type_counts[t] = type_counts.get(t, 0) + 1
            except json.JSONDecodeError:
                pass
    return type_counts


def print_type_summary(type_counts: dict, filepath: Path):
    """打印 type 汇总表格"""
    global _CONSOLE

    _CONSOLE.print(f"\n{'=' * 66}")
    _CONSOLE.print(f"  type 汇总 — {filepath.name}")
    _CONSOLE.print(f"{'=' * 66}")
    total = sum(type_counts.values())
    if not type_counts:
        _CONSOLE.print("  (无数据)")
    else:
        max_cnt = max(type_counts.values())
        for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            bar_len = min(30, cnt * 30 // max_cnt) if max_cnt else 0
            bar = '█' * bar_len
            _CONSOLE.print(f"  {t:<32} {cnt:>6}  {bar}")
        _CONSOLE.print(f"  {'─' * 32}  {'─' * 6}")
        _CONSOLE.print(f"  {'总计':<32} {total:>6}")
    _CONSOLE.print(f"{'=' * 66}\n")


def _format_size(size_bytes: int) -> str:
    """将字节数转为人类可读的文件大小"""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == 'B' else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def list_jsonl_files() -> list[dict]:
    """列出项目目录下所有 jsonl 文件，按修改时间降序"""
    project_dir = get_project_dir()
    if project_dir is None:
        return []

    files = []
    for f in sorted(project_dir.glob('*.jsonl'), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append({
            '文件名': f.name,
            '修改时间': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            '大小': _format_size(stat.st_size),
        })
    return files


def print_files_table(files: list[dict]):
    """用 rich 表格打印 jsonl 文件列表"""
    global _CONSOLE
    if not files:
        _CONSOLE.print("[yellow]目录下没有 .jsonl 文件[/yellow]")
        return

    project_dir = get_project_dir()
    table = Table(title=f"JSONL 文件列表 — {project_dir}" if project_dir else "JSONL 文件列表")
    table.add_column("文件名", style="cyan", no_wrap=True)
    table.add_column("修改时间", style="green")
    table.add_column("大小", style="yellow", justify="right")

    for f in files:
        table.add_row(f['文件名'], f['修改时间'], f['大小'])

    _CONSOLE.print(table)


def _traverse_path(value, parts: List[str]):
    """
    沿 parts 路径递归遍历 value，支持 dict 和 list 两种容器。

    - dict: 按 key 取值
    - list: 遍历每个元素，对每个元素递归匹配剩余路径，收集所有非 None 结果；
            若全为字符串则拼接（用 \\n 分隔），否则返回列表
    """
    if not parts:
        return value

    part = parts[0]
    rest = parts[1:]

    if isinstance(value, dict):
        child = value.get(part)
        return _traverse_path(child, rest)

    if isinstance(value, list):
        collected = []
        for item in value:
            if isinstance(item, dict) and part in item:
                v = _traverse_path(item[part], rest)
                if v is not None:
                    collected.append(v)
            elif isinstance(item, list):
                # 递归展平嵌套列表
                v = _traverse_path(item, parts)
                if v is not None:
                    if isinstance(v, list):
                        collected.extend(v)
                    else:
                        collected.append(v)

        if not collected:
            return None
        if all(isinstance(x, str) for x in collected):
            return '\n'.join(collected)
        return collected

    # 纯字符串作为 content 时的兼容：message.content 可能是 "..." 而非 [{type:"text",text:"..."}]
    # 此时 message.content.text 应等价于 message.content 本身
    if isinstance(value, str) and part == 'text' and not rest:
        return value

    return None


def extract_fields(obj: dict, fields: List[str]) -> dict:
    """
    从 JSON 对象中提取指定字段，支持任意深度嵌套字段（用 . 分隔），
    并能穿透 list 结构（如 message.content.text 中 content 为 [{type:\"text\",text:\"...\"}]）。
    """
    result = {}
    for field in fields:
        parts = field.split('.')
        result[field] = _traverse_path(obj, parts)
    return result


def format_value(value, indent: int = 0) -> str:
    """
    格式化输出值：
    - dict / list / tuple: 转为 JSON 字符串（保留结构可见，不与纯文本混淆）
    - str 非空: 将字面量 \\n/\\r 转为实际换行，多行加缩进
    - str 空值 / None: 返回占位符
    """
    if value is None:
        return "(null)"

    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, indent=2)

    if isinstance(value, str):
        if not value:
            return "(empty str)"

        indent_str = '  ' * indent

        # JSON 中可能保留了字面量 \\n（即两个字符 \ 和 n），将其转为真实换行
        if '\\n' in value:
            value = value.replace('\\n', '\n')
        if '\\r\\n' in value:
            value = value.replace('\\r\\n', '\r\n')
        if '\\t' in value:
            value = value.replace('\\t', '\t')

        # 多行字符串：每行加缩进
        if '\n' in value or '\r\n' in value:
            result_lines = []
            for raw_line in value.split('\n'):
                line = raw_line.strip('\r')
                result_lines.append(f'{indent_str}{line}' if line else '')
            return '\n'.join(result_lines)
        return f'{indent_str}{value}' if indent > 0 else value

    return str(value)


def process_line(line: str, fields: List[str], must_fields: Optional[List[str]] = None,
                  show_all: bool = False) -> Optional[dict]:
    """
    处理单行 JSONL 数据。若指定了 must_fields，则依次判断每个 must-field：
    - 值不是 dict（且非 None）→ 满足 → 保留该行
    - 值是 dict → 不满足 → 继续判断下一个
    - 全部 must-field 都不满足 → 整行跳过（返回 None）
    """
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)

        # must-field 过滤：至少有一个 must-field 的值不是 dict 才保留
        if must_fields:
            satisfied = False
            for mf in must_fields:
                v = _traverse_path(data, mf.split('.'))
                if v is not None and not isinstance(v, dict):
                    satisfied = True
                    break
            if not satisfied:
                return None

        extracted = extract_fields(data, fields)
        return extracted
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}")
        return None


def _fmt_entry(entry: dict, fields: List[str], must_fields: Optional[List[str]] = None) -> str:
    """将单条提取结果格式化为多行字符串。must-field 标签用红色，其余用绿色。"""
    mf_set = set(must_fields or [])
    lines = []
    for field in fields:
        value = entry.get(field)
        if value is None:
            continue
        label = field
        color = 'red' if field in mf_set else 'green'
        formatted = format_value(value, indent=0)

        if '\n' in formatted:
            # 多行内容：标签单独一行，内容不额外缩进
            lines.append(f"  [{color}]{label}[/{color}]:")
            for fline in formatted.split('\n'):
                lines.append(fline)
        else:
            lines.append(f"  [{color}]{label}[/{color}]: [yellow]{formatted}[/yellow]")
    return '\n'.join(lines)


def _flush_group(entries: list[dict], fields: List[str], msg_id: str = '',
                  must_fields: Optional[List[str]] = None):
    """输出一个 messageId 分组内的所有条目"""
    global _CONSOLE
    if not entries:
        return

    mid_display = msg_id if msg_id else '(无 messageId)'
    _CONSOLE.print(f"\n── [cyan]{mid_display}[/cyan] ──")
    for entry in entries:
        _CONSOLE.print(_fmt_entry(entry, fields, must_fields))
        _CONSOLE.print()  # 同组内各条目之间空行

def _scan_matching_prompt_ids(filepath: Path, search_text: str) -> set:
    """
    第一遍扫描：逐行读取原始 jsonl 文本，若行中包含 search_text 且可提取
    到 promptId，则收集该 promptId。不做结构化解析，直接对原始字符串匹配。
    """
    matching: set[str] = set()
    with open(filepath, 'r', encoding='utf-8') as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or search_text not in stripped:
                continue
            try:
                data = json.loads(stripped)
                pid = data.get('promptId', '')
                if pid:
                    matching.add(pid)
            except Exception:
                pass
    return matching


def tail_file(filepath: Path, fields: List[str], must_fields: Optional[List[str]] = None,
              follow: bool = True, show_all: bool = False, tail_mode: bool = False,
              find_user_message: Optional[str] = None):
    """
    读取（并可选择持续监听）JSONL 文件，按 messageId 分组输出提取字段。
    tail_mode=True 时从文件末尾开始，仅输出新写入的行。
    must_fields: 可选，每条记录在这些字段上的值必须为 str 才输出。
    """
    if not filepath.exists():
        logger.error(f"文件不存在: {filepath}")
        return

    logger.info(f"文件: {filepath}")
    logger.info(f"提取字段: {', '.join(fields)}")
    if must_fields:
        logger.info(f"必须字段 (值非 dict 即满足): {', '.join(must_fields)}")

    # 初始扫描：收集匹配的 promptId
    prompt_filter: Optional[set] = None
    if find_user_message:
        prompt_filter = _scan_matching_prompt_ids(filepath, find_user_message)
        logger.info(f"find-user-message: '{find_user_message}' → {len(prompt_filter)} 个 promptId: {prompt_filter}")
        if not prompt_filter:
            _CONSOLE.print(f"[yellow]未找到包含 '{find_user_message}' 的用户消息[/yellow]")
            return

    pending: list[tuple[str, list[dict]]] = []  # [(mid, [entry, ...]), ...]

    def _flush_all():
        """输出所有待定分组"""
        for mid, entries in pending:
            _flush_group(entries, fields, mid, must_fields)
        pending.clear()

    def _ingest_batch(groups: list[tuple[str, list[dict]]]):
        """
        将新读取的 groups 合并到 pending 中：
        - groups[0:-1] 已确认完整（因为下一 messageId 已经出现），直接输出；
        - groups[-1] 有可能在后续读取中继续增长，合并到 pending 尾部。
        """
        if not groups:
            return

        # 输出已确认完整的分组
        for mid, entries in groups[:-1]:
            _flush_group(entries, fields, mid, must_fields)

        # 最后一条与新读到的合并
        last_mid, last_entries = groups[-1]
        if pending and pending[-1][0] == last_mid:
            pending[-1][1].extend(last_entries)
        else:
            # 新的 messageId — 之前的 pending 已完整
            if pending:
                _flush_group(pending[-1][1], fields, pending[-1][0], must_fields)
                pending.clear()
            pending.append((last_mid, last_entries))

    def _read_batch(f) -> tuple[list[tuple[str, list[dict]]], bool]:
        """从当前文件指针读取所有可读行，按 messageId 分组"""
        nonlocal prompt_filter
        groups: list[tuple[str, list[dict]]] = []
        truncated = False
        while True:
            where = f.tell()
            line = f.readline()
            if not line:
                break

            # 单次解析 JSON，兼顾 messageId / promptId
            try:
                raw = json.loads(line.strip())
            except Exception:
                continue

            # promptId 动态发现（follow 模式下新写入的匹配行会被捕获）
            if find_user_message and prompt_filter is not None:
                stripped = line.strip()
                if find_user_message in stripped:
                    try:
                        pid = json.loads(stripped).get('promptId', '')
                        if pid and pid not in prompt_filter:
                            prompt_filter.add(pid)
                            logger.info(f"动态发现新匹配 promptId: {pid}")
                    except Exception:
                        pass

            # promptId 过滤：仅对带 promptId 的行生效；无 promptId 的行（系统事件等）放行
            if prompt_filter is not None:
                pid = raw.get('promptId', '')
                if pid and pid not in prompt_filter:
                    continue

            data = process_line(line, fields, must_fields, show_all)
            if data is None:
                continue

            mid = raw.get('messageId', '')
            if groups and groups[-1][0] == mid:
                groups[-1][1].append(data)
            else:
                groups.append((mid, [data]))

            if filepath.stat().st_size < where:
                truncated = True
                break
        return groups, truncated

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            if tail_mode:
                f.seek(0, os.SEEK_END)
                logger.info("从文件末尾开始 (--tail)")
            else:
                logger.info("从文件开头开始读取")

            while True:
                groups, truncated = _read_batch(f)

                if truncated:
                    logger.info("文件被轮转，重新从开头读取")
                    _flush_all()
                    f.seek(0)
                    continue

                _ingest_batch(groups)

                if follow:
                    # 已读到 EOF，pending 中若有数据则输出（保证用户及时看到）
                    _flush_all()
                    time.sleep(0.5)
                else:
                    _flush_all()
                    break

    except KeyboardInterrupt:
        _flush_all()
        logger.info("用户中断监听")
    except Exception as e:
        logger.error(f"监听出错: {e}")


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option(
    '--file', '-f',
    type=click.Path(path_type=Path),
    required=False,
    help='要监听的 JSONL 文件路径（不指定则自动选择 $HOME/.claude/projects/{当前目录转义}/ 下最新修改的 .jsonl 文件）'
)
@click.option(
    '--field', '-F', 'fields',
    multiple=True,
    callback=split_comma,
    default=['timestamp', 'type', 'message.role', 'message.content.name'],
    help='要提取的字段，用逗号分隔，支持嵌套字段如 message.content (默认: timestamp,type,message,content)'
)
@click.option(
    '--no-follow', '-nf',
    is_flag=True,
    help='不持续监听，只读取一次现有内容'
)
@click.option(
    '--show-all', '-a',
    is_flag=True,
    help='显示所有字段（包括未提取到的）'
)
@click.option(
    '--list-types', '-lt',
    is_flag=True,
    help='扫描文件，显示所有 type 值的出现次数汇总'
)
@click.option(
    '--list-files', '-lf',
    is_flag=True,
    help='列出默认目录下所有 jsonl 文件及其修改时间（最近的排最前）'
)
@click.option(
    '--tail', '-t',
    is_flag=True,
    help='从文件末尾开始监听（类似 tail -f），不输出已有内容'
)
@click.option(
    '--must-field', '-mf', 'must_fields',
    multiple=True,
    callback=split_comma,
    default=['message.content.text',],
    help='必须字段过滤：若某 must-field 值为 dict 则不满足，继续判断下一个；全部都不满足则跳过该行。支持嵌套字段，可多次指定或逗号分隔'
)
@click.option(
    '--find-user-message', '-fum',
    type=str,
    default=None,
    help='查找 user 消息中包含指定字符串的 promptId，仅显示该轮对话的所有消息'
)
def main(file: Path, fields: list[str], no_follow: bool, show_all: bool,
         list_types: bool, list_files: bool, tail: bool, must_fields: list[str],
         find_user_message: Optional[str]):
    """
    持续监听 JSONL 文件并按 messageId 分组提取指定字段。

    示例：

    \b
    # 自动选最新文件，持续监听
    python listen_cc_jsonl.py

    \b
    # 列出所有 jsonl 文件及修改时间
    python listen_cc_jsonl.py --list-files

    \b
    # 查看文件包含哪些 type
    python listen_cc_jsonl.py --list-types

    \b
    # 从文件末尾开始监听（跳过已有内容）
    python listen_cc_jsonl.py --tail

    \b
    # 自定义字段 + 从尾部监听
    python listen_cc_jsonl.py -F "type,message.role,message.content.text" -t

    \b
    # 只读取一次，不持续监听
    python listen_cc_jsonl.py --no-follow

    \b
    # 只显示 message.content.text 值不是 dict 的行（如过滤掉纯 thinking/tool_use 行）
    python listen_cc_jsonl.py -mf message.content.text

    \b
    # 查找包含特定关键词的 user 消息，仅显示该轮对话
    python listen_cc_jsonl.py -fum "回测"
    """

    # --list-files：列出默认目录下所有 jsonl 文件（不依赖具体文件）
    if list_files:
        files = list_jsonl_files()
        print_files_table(files)
        return

    # 解析文件路径：未指定则自动选最新，裸文件名则补全项目目录路径
    if file is None:
        file = get_default_jsonl_file()
    elif len(file.parts) == 1:
        # 裸文件名（无目录部分）→ 自动补全项目目录 + .jsonl 后缀
        name = file.name
        if not name.endswith('.jsonl'):
            name += '.jsonl'
        project_dir = get_project_dir()
        if project_dir is None:
            logger.error("默认项目目录不存在，无法解析文件名。请使用完整路径的 --file。")
            sys.exit(1)
        file = project_dir / name
        logger.info(f"解析文件名 → {file}")

    if file is None:
        logger.error(
            "未指定 --file 且无法自动找到 JSONL 文件。"
            "请确保 $HOME/.claude/projects/{当前目录转义}/ 目录下存在 .jsonl 文件，"
            "或通过 --file 手动指定文件路径。"
        )
        sys.exit(1)

    # 校验文件存在
    if not file.exists():
        logger.error(f"文件不存在: {file}")
        sys.exit(1)

    # --list-types：扫描并显示 type 汇总后退出
    if list_types:
        type_counts = list_file_types(file)
        print_type_summary(type_counts, file)
        return

    # 解析字段
    # fields 必须包含 must_fields，否则可能导致 must-field 过滤失效
    fields = list(set(fields) | set(must_fields))
    if not fields:
        logger.error("至少需要指定一个字段")
        sys.exit(1)

    # 开始监听
    tail_file(file, fields, must_fields=must_fields,
              follow=not no_follow, show_all=show_all, tail_mode=tail,
              find_user_message=find_user_message)


if __name__ == '__main__':
    main()