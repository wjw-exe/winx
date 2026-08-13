#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Winux v1.0 - 跨平台命令行文件管理器
让 Windows 用户畅享 Linux 式的命令体验
支持 Windows / Linux / macOS
"""

import os
import sys
import shutil
import hashlib
import zipfile
import tarfile
import fnmatch
import time
import re
import json
import platform
import subprocess
import msvcrt
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ============================================================
#  跨平台 readline 兼容
# ============================================================
READLINE_AVAILABLE = False
readline = None

if platform.system() == "Windows":
    try:
        from pyreadline3 import Readline
        readline = Readline()
        READLINE_AVAILABLE = True
    except ImportError:
        try:
            from pyreadline import Readline
            readline = Readline()
            READLINE_AVAILABLE = True
        except ImportError:
            READLINE_AVAILABLE = False
else:
    try:
        import readline
        READLINE_AVAILABLE = True
    except ImportError:
        READLINE_AVAILABLE = False

# ============================================================
#  颜色 & 图标
# ============================================================
class C:
    """ANSI 颜色（Windows 10+ 原生支持）"""
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    MAGENTA= "\033[95m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"
    INVERSE = "\033[7m"
    UNDERLINE = "\033[4m"

# Windows 旧版控制台启用 ANSI
if platform.system() == "Windows":
    os.system("")

# 文件类型 → 颜色
COLOR_MAP = {
    "py": C.GREEN, "pyw": C.GREEN,
    "js": C.YELLOW, "ts": C.YELLOW, "json": C.YELLOW,
    "html": C.CYAN, "css": C.CYAN, "xml": C.CYAN,
    "md": C.BLUE, "txt": C.BLUE, "rst": C.BLUE,
    "png": C.MAGENTA, "jpg": C.MAGENTA, "jpeg": C.MAGENTA,
    "gif": C.MAGENTA, "bmp": C.MAGENTA, "svg": C.MAGENTA, "webp": C.MAGENTA,
    "mp3": C.RED, "wav": C.RED, "flac": C.RED, "aac": C.RED,
    "mp4": C.RED, "avi": C.RED, "mkv": C.RED, "mov": C.RED,
    "zip": C.YELLOW, "tar": C.YELLOW, "gz": C.YELLOW, "rar": C.YELLOW, "7z": C.YELLOW,
    "pdf": C.RED, "doc": C.BLUE, "docx": C.BLUE, "xls": C.GREEN, "xlsx": C.GREEN,
    "exe": C.RED, "msi": C.RED, "bat": C.RED, "cmd": C.RED, "ps1": C.RED,
}

# 文件类型 → 图标
ICON_MAP = {
    "py": "🐍", "pyw": "🐍",
    "js": "📜", "ts": "📜", "json": "📋",
    "html": "🌐", "css": "🎨",
    "md": "📝", "txt": "📄", "rst": "📄",
    "png": "🖼️", "jpg": "🖼️", "jpeg": "🖼️", "gif": "🖼️", "svg": "🖼️", "webp": "🖼️",
    "mp3": "🎵", "wav": "🎵", "flac": "🎵",
    "mp4": "🎬", "avi": "🎬", "mkv": "🎬", "mov": "🎬",
    "zip": "📦", "tar": "📦", "gz": "📦", "rar": "📦", "7z": "📦",
    "pdf": "📕", "doc": "📘", "docx": "📘", "xls": "📗", "xlsx": "📗",
    "exe": "⚙️", "bat": "⚙️", "cmd": "⚙️", "ps1": "⚙️",
}

# ============================================================
#  工具函数
# ============================================================

def colorize(text, color):
    return f"{color}{text}{C.RESET}"

def get_icon(name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ICON_MAP.get(ext, "📄")

def get_color(name, is_dir=False):
    if is_dir:
        return C.BLUE + C.BOLD
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return COLOR_MAP.get(ext, C.RESET)

def format_size(size):
    """人类可读大小"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

def format_perm(mode):
    """rwx 权限字符串"""
    if platform.system() == "Windows":
        return "rw-" if os.access else "---"
    perm = ""
    for shift in [6, 3, 0]:
        triplet = (mode >> shift) & 0o7
        perm += "r" if triplet & 4 else "-"
        perm += "w" if triplet & 2 else "-"
        perm += "x" if triplet & 1 else "-"
    return perm

def format_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def safe_input(prompt=""):
    """兼容 Windows 的输入"""
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        return None

# ============================================================
#  内嵌 Nano 风格文本编辑器
# ============================================================

class NanoEditor:
    """
    迷你 nano 风格编辑器，Windows 下用 msvcrt 实现逐字符输入。
    支持：输入、Backspace 删除、Delete 删除、方向键移动光标、
          Enter 换行、Tab 缩进、Ctrl+S 保存、Ctrl+X 退出、Ctrl+W 查找
    """

    def __init__(self, filepath):
        self.filepath = filepath
        self.modified = False
        # 读取文件内容到行列表
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                self.lines = content.split("\n")
        except FileNotFoundError:
            self.lines = [""]
        if not self.lines:
            self.lines = [""]

        # 光标位置
        self.cur_row = 0
        self.cur_col = 0
        self.row_offset = 0  # 视口滚动偏移

    # ---------- 光标约束 ----------
    def _clamp_cursor(self):
        self.cur_row = max(0, min(self.cur_row, len(self.lines) - 1))
        self.cur_col = max(0, min(self.cur_col, len(self.lines[self.cur_row])))

    # ---------- 渲染 ----------
    def _get_terminal_height(self):
        try:
            return shutil.get_terminal_size().lines
        except:
            return 24

    def _get_terminal_width(self):
        try:
            return shutil.get_terminal_size().columns
        except:
            return 80

    def _render(self):
        h = self._get_terminal_height() - 2  # 留 2 行给状态栏
        self.row_offset = max(0, min(self.row_offset, self.cur_row))
        if self.cur_row >= self.row_offset + h:
            self.row_offset = self.cur_row - h + 1

        # 清屏 + 光标回左上角
        sys.stdout.write("\033[2J\033[H")

        # 绘制可见行
        for i in range(h):
            abs_row = self.row_offset + i
            if abs_row >= len(self.lines):
                sys.stdout.write("\n")
                continue
            line_no = colorize(f"{abs_row+1:>4}", C.GRAY)
            line_text = self.lines[abs_row]

            if abs_row == self.cur_row:
                col = self.cur_col
                if col < len(line_text):
                    before = line_text[:col]
                    char = line_text[col]
                    after = line_text[col+1:]
                    disp = before + colorize(char, C.INVERSE + C.BOLD) + after
                else:
                    disp = line_text + colorize(" ", C.INVERSE)
            else:
                disp = line_text

            # 截断超宽行
            max_w = self._get_terminal_width() - 7
            if len(disp) > max_w:
                disp = disp[:max_w]
            sys.stdout.write(f"\r{line_no} │ {disp}\n")

        # 状态栏（反色）
        sys.stdout.write("\033[7m")
        mod_mark = " **[已修改]**" if self.modified else ""
        status = f" {os.path.basename(self.filepath)}{mod_mark}  |  行 {self.cur_row+1}/{len(self.lines)}  列 {self.cur_col+1}  |  Ctrl+S:保存  Ctrl+X:退出  Ctrl+W:查找  Tab:缩进"
        cols = self._get_terminal_width()
        sys.stdout.write(status.ljust(cols)[:cols])
        sys.stdout.write("\033[0m\n")
        sys.stdout.flush()

    # ---------- 保存 ----------
    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines))
            self.modified = False
            return True
        except OSError:
            return False

    # ---------- 查找 ----------
    def _find(self):
        """简单查找功能"""
        sys.stdout.write("\033[2J\033[H")
        print(colorize("🔍 查找 (输入关键字后回车):", C.YELLOW), end="", flush=True)

        query = ""
        while True:
            ch = msvcrt.getch()
            code = ch[0] if isinstance(ch, bytes) else ord(ch)

            # Enter 确认
            if code == 13:
                break
            # Escape 取消
            if code == 27:
                query = ""
                break
            # Backspace
            elif code == 8:
                if query:
                    query = query[:-1]
                    sys.stdout.write("\b \b")
            # 可打印字符
            elif 32 <= code < 127:
                query += ch.decode("utf-8", errors="replace")
                sys.stdout.write(ch.decode("utf-8", errors="replace"))
            sys.stdout.flush()

        if query:
            for i in range(self.cur_row + 1, len(self.lines)):
                if query.lower() in self.lines[i].lower():
                    self.cur_row = i
                    idx = self.lines[i].lower().find(query.lower())
                    self.cur_col = idx
                    self._clamp_cursor()
                    return
            # 从开头再找一次
            for i in range(self.cur_row + 1):
                if query.lower() in self.lines[i].lower():
                    self.cur_row = i
                    idx = self.lines[i].lower().find(query.lower())
                    self.cur_col = idx
                    self._clamp_cursor()
                    return

    # ---------- 主循环 ----------
    def run(self):
        """编辑器主循环"""
        while True:
            self._clamp_cursor()
            self._render()

            ch = msvcrt.getch()
            code = ch[0] if isinstance(ch, bytes) else ord(ch)

            # ---- 扩展键（方向键 / Delete 等）----
            if code == 0 or code == 224:
                ch2 = msvcrt.getch()
                code2 = ch2[0] if isinstance(ch2, bytes) else ord(ch2)
                if code2 == 72:    # 上箭头
                    self.cur_row -= 1
                elif code2 == 80:  # 下箭头
                    self.cur_row += 1
                elif code2 == 75:  # 左箭头
                    self.cur_col -= 1
                elif code2 == 77:  # 右箭头
                    self.cur_col += 1
                elif code2 == 71:  # Home
                    self.cur_col = 0
                elif code2 == 79:  # End
                    self.cur_col = len(self.lines[self.cur_row])
                elif code2 == 73:  # Page Up
                    self.cur_row -= 10
                elif code2 == 81:  # Page Down
                    self.cur_row += 10
                elif code2 == 83:  # Delete
                    line = self.lines[self.cur_row]
                    if self.cur_col < len(line):
                        self.lines[self.cur_row] = line[:self.cur_col] + line[self.cur_col+1:]
                        self.modified = True
                continue

            # ---- Ctrl 组合键 ----
            # Ctrl+S (0x13) 保存
            if code == 0x13:
                if self._save():
                    sys.stdout.write("\033[2J\033[H")
                    print(colorize(f"  ✔ 已保存: {self.filepath}", C.GREEN))
                    msvcrt.getch()  # 等待任意键
                continue

            # Ctrl+X (0x18) 退出
            if code == 0x18:
                if self.modified:
                    sys.stdout.write("\033[2J\033[H")
                    print(colorize("  ⚠ 文件已修改但未保存", C.YELLOW))
                    print(colorize("  按 Y 保存并退出 | N 放弃退出 | Esc 取消: ", C.YELLOW), end="", flush=True)
                    while True:
                        confirm = msvcrt.getch()
                        c = confirm.upper()
                        if c == b"Y":
                            self._save()
                            break
                        elif c == b"N":
                            break
                        elif c == b"\x1b":  # Esc
                            continue
                        continue
                    # 如果按了 Y/N/Esc 以外的键，再读一次
                sys.stdout.write("\033[2J\033[H")
                return

            # Ctrl+W (0x17) 查找
            if code == 0x17:
                self._find()
                continue

            # Ctrl+G (0x07) 跳转到行
            if code == 0x07:
                sys.stdout.write("\033[2J\033[H")
                print(colorize("⤴ 跳转到行号:", C.YELLOW), end="", flush=True)
                num = ""
                while True:
                    ch_g = msvcrt.getch()
                    cg = ch_g[0] if isinstance(ch_g, bytes) else ord(ch_g)
                    if cg == 13:  # Enter
                        break
                    elif cg == 8:  # Backspace
                        num = num[:-1]
                        sys.stdout.write("\b \b")
                    elif 48 <= cg <= 57:  # 数字
                        num += ch_g.decode("utf-8")
                        sys.stdout.write(ch_g.decode("utf-8"))
                    sys.stdout.flush()
                if num.isdigit():
                    self.cur_row = int(num) - 1
                    self.cur_col = 0
                continue

            # Ctrl+A (0x01) 跳到文件末尾
            if code == 0x01:
                self.cur_row = len(self.lines) - 1
                self.cur_col = len(self.lines[-1])
                continue

            # ---- 普通按键 ----

            # Enter (\r) 换行
            if code == 13:
                line = self.lines[self.cur_row]
                new_line = line[self.cur_col:]
                self.lines[self.cur_row] = line[:self.cur_col]
                self.lines.insert(self.cur_row + 1, new_line)
                self.cur_row += 1
                self.cur_col = 0
                self.modified = True
                continue

            # Backspace (\x08) 删除前一字符
            if code == 8:
                if self.cur_col > 0:
                    line = self.lines[self.cur_row]
                    self.lines[self.cur_row] = line[:self.cur_col-1] + line[self.cur_col:]
                    self.cur_col -= 1
                    self.modified = True
                elif self.cur_row > 0:
                    # 合并到上一行
                    prev = self.lines[self.cur_row - 1]
                    cur = self.lines[self.cur_row]
                    self.cur_col = len(prev)
                    self.lines[self.cur_row - 1] = prev + cur
                    del self.lines[self.cur_row]
                    self.cur_row -= 1
                    self.modified = True
                continue

            # Tab 键插入 4 空格
            if code == 9:
                line = self.lines[self.cur_row]
                self.lines[self.cur_row] = line[:self.cur_col] + "    " + line[self.cur_col:]
                self.cur_col += 4
                self.modified = True
                continue

            # Escape 显示帮助
            if code == 27:
                sys.stdout.write("\033[2J\033[H")
                print(colorize("  ╔════════════════════════════════════════╗", C.CYAN))
                print(colorize("  ║     📝  Nano 编辑器快捷键帮助         ║", C.CYAN))
                print(colorize("  ╠════════════════════════════════════════╣", C.CYAN))
                print(colorize("  ║  Ctrl+S  - 保存文件                  ║", C.CYAN))
                print(colorize("  ║  Ctrl+X  - 退出（有修改时提示）      ║", C.CYAN))
                print(colorize("  ║  Ctrl+W  - 查找文本                  ║", C.CYAN))
                print(colorize("  ║  Ctrl+G  - 跳转到指定行              ║", C.CYAN))
                print(colorize("  ║  Ctrl+A  - 跳到文件末尾              ║", C.CYAN))
                print(colorize("  ║  Tab     - 插入4空格缩进             ║", C.CYAN))
                print(colorize("  ║  方向键  - 移动光标                  ║", C.CYAN))
                print(colorize("  ║  Home/End- 行首/行尾                 ║", C.CYAN))
                print(colorize("  ║  Delete  - 删除光标后字符            ║", C.CYAN))
                print(colorize("  ║  Backspc - 删除光标前字符            ║", C.CYAN))
                print(colorize("  ╚════════════════════════════════════════╝", C.CYAN))
                print(colorize("  按任意键继续...", C.GRAY), end="", flush=True)
                msvcrt.getch()
                continue

            # 可打印字符（含中文等多字节）
            if code >= 32:
                try:
                    char = ch.decode("utf-8", errors="ignore")
                    if char:
                        line = self.lines[self.cur_row]
                        self.lines[self.cur_row] = line[:self.cur_col] + char + line[self.cur_col:]
                        self.cur_col += 1
                        self.modified = True
                except:
                    pass


# ============================================================
#  Winux 文件管理器主类
# ============================================================

class Winux:
    VERSION = "1.0"
    NAME = "Winux"

    def __init__(self, start_dir=None):
        self.current_dir = os.path.abspath(start_dir or os.getcwd())
        self.bookmarks = self._load_bookmarks()
        self.history = []
        self.max_history = 100
        self.clipboard = None
        self.apt_backend = self._detect_apt_backend()
        self._init_readline()

    # ---------- 初始化 ----------
    def _init_readline(self):
        if READLINE_AVAILABLE and readline:
            readline.set_completer(self._tab_completer)
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" \t\n;")

    def _tab_completer(self, text, state):
        """Tab 补全：补全命令名和文件路径"""
        line = readline.get_line_buffer() if READLINE_AVAILABLE else ""
        parts = line.split()

        if not parts or (len(parts) == 1 and not line.endswith(" ")):
            matches = [c for c in self.COMMANDS if c.startswith(text)]
        else:
            matches = []
            prefix = text if text else ""
            dir_part = os.path.dirname(prefix) or self.current_dir
            base = os.path.basename(prefix)
            try:
                for item in os.listdir(dir_part):
                    if item.startswith(base):
                        full = os.path.join(dir_part, item)
                        display = item + ("/" if os.path.isdir(full) else " ")
                        matches.append(display)
            except OSError:
                pass

        if state < len(matches):
            return matches[state]
        return None

    # ---------- 包管理器后端检测 ----------
    def _detect_apt_backend(self):
        """检测可用的 Windows 包管理器"""
        if platform.system() != "Windows":
            return None
        for cmd in ["winget", "choco", "scoop"]:
            try:
                subprocess.run([cmd, "--version"], capture_output=True, timeout=3)
                return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None

    # ---------- 书签 ----------
    def _load_bookmarks(self):
        path = os.path.expanduser("~/.winux_bookmarks.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_bookmarks(self):
        path = os.path.expanduser("~/.winux_bookmarks.json")
        try:
            with open(path, "w") as f:
                json.dump(self.bookmarks, f, indent=2)
        except OSError:
            pass

    # ---------- 主循环 ----------
    def run(self):
        self._print_banner()
        while True:
            try:
                prompt = f"\n{colorize(self.current_dir, C.CYAN)} {C.BOLD}❯{C.RESET} "
                cmd_line = safe_input(prompt)
                if cmd_line is None:
                    print("\n再见！")
                    break
                cmd_line = cmd_line.strip()
                if not cmd_line:
                    continue

                self.history.append(cmd_line)
                if len(self.history) > self.max_history:
                    self.history = self.history[-self.max_history:]

                self._execute(cmd_line)

            except KeyboardInterrupt:
                print("\n提示：输入 'quit' 或按 Ctrl+D 退出")
            except Exception as e:
                print(colorize(f"  ✖ 错误: {e}", C.RED))

    def _print_banner(self):
        bar = "═" * 56
        print(colorize(f"╔{bar}╗", C.BLUE))
        print(colorize(f"║    🐧  {self.NAME} v{self.VERSION}  -  命令行文件管理器     ║", C.BLUE))
        print(colorize(f"║    💡  Windows + Linux = Winux                    ║", C.BLUE))
        print(colorize(f"╚{bar}╝", C.BLUE))
        print(f"\n  当前目录: {self.current_dir}")
        print(f"  输入 'help' 查看帮助, 'quit' 退出")
        if not READLINE_AVAILABLE:
            print(colorize("  ⚠ Tab 补全不可用（安装 pyreadline3 可启用）", C.YELLOW))
        if self.apt_backend:
            print(colorize(f"  ✔ 包管理器后端: {self.apt_backend}", C.GREEN))
        else:
            print(colorize("  ⚠ 未检测到 winget/choco/scoop，apt 命令不可用", C.YELLOW))

    # ---------- 命令分发 ----------
    COMMANDS = [
        "ls", "ll", "cd", "pwd", "back", "tree",
        "mkdir", "touch", "rm", "cp", "mv", "rename",
        "cat", "head", "tail", "diff",
        "find", "info", "du", "stats",
        "zip", "unzip", "tar",
        "bulk-rename", "chmod",
        "open", "edit", "nano",
        "apt",
        "bookmark", "bm",
        "history", "clear", "cls", "help", "quit", "exit",
    ]

    def _execute(self, cmd_line):
        parts = cmd_line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        handlers = {
            "ls": self.cmd_ls, "ll": self.cmd_ll,
            "cd": self.cmd_cd, "pwd": self.cmd_pwd,
            "back": self.cmd_back, "tree": self.cmd_tree,
            "mkdir": self.cmd_mkdir, "touch": self.cmd_touch,
            "rm": self.cmd_rm, "cp": self.cmd_cp, "mv": self.cmd_mv,
            "rename": self.cmd_rename,
            "cat": self.cmd_cat, "head": self.cmd_head, "tail": self.cmd_tail,
            "diff": self.cmd_diff,
            "find": self.cmd_find, "info": self.cmd_info,
            "du": self.cmd_du, "stats": self.cmd_stats,
            "zip": self.cmd_zip, "unzip": self.cmd_unzip, "tar": self.cmd_tar,
            "bulk-rename": self.cmd_bulk_rename, "chmod": self.cmd_chmod,
            "open": self.cmd_open,
            "edit": self.cmd_edit, "nano": self.cmd_edit,
            "apt": self.cmd_apt,
            "bookmark": self.cmd_bookmark, "bm": self.cmd_bookmark,
            "history": self.cmd_history,
            "clear": self.cmd_clear, "cls": self.cmd_clear,
            "help": self.cmd_help, "quit": self.cmd_quit, "exit": self.cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            handler(args)
        else:
            print(colorize(f"  未知命令: {cmd}", C.RED))
            print(f"  输入 'help' 查看可用命令")

    # ==================== 导航 ====================

    def cmd_ls(self, args):
        """ls [-l] [-a] [-s] [path]"""
        show_hidden = "-a" in args or "-all" in args
        long_form = "-l" in args or "-long" in args
        sort_by_size = "-s" in args or "-size" in args

        target = self.current_dir
        for a in args:
            if not a.startswith("-"):
                target = self._resolve_path(a)
                break

        if not os.path.isdir(target):
            print(colorize(f"  不是目录: {target}", C.RED))
            return

        items = os.listdir(target)
        if not show_hidden:
            items = [i for i in items if not i.startswith(".")]

        entries = []
        for name in items:
            full = os.path.join(target, name)
            try:
                st = os.stat(full)
                entries.append({
                    "name": name, "is_dir": os.path.isdir(full),
                    "size": st.st_size, "mtime": st.st_mtime, "mode": st.st_mode,
                })
            except OSError:
                entries.append({"name": name, "is_dir": False, "size": 0, "mtime": 0, "mode": 0})

        if sort_by_size:
            entries.sort(key=lambda e: e["size"], reverse=True)
        else:
            entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

        if long_form:
            total = sum(e["size"] for e in entries if not e["is_dir"])
            print(colorize(f"  总计: {format_size(total)} ({len(entries)} 项)", C.GRAY))
            for e in entries:
                icon = "📁" if e["is_dir"] else get_icon(e["name"])
                color = get_color(e["name"], e["is_dir"])
                perm = format_perm(e["mode"])
                size_s = format_size(e["size"]) if not e["is_dir"] else "-"
                time_s = format_time(e["mtime"])
                name_s = colorize(e["name"] + ("/" if e["is_dir"] else ""), color)
                print(f"  {perm}  {size_s:>10}  {time_s}  {icon} {name_s}")
        else:
            cols = 2 if platform.system() == "Windows" else 3
            for i, e in enumerate(entries):
                icon = "📁" if e["is_dir"] else get_icon(e["name"])
                color = get_color(e["name"], e["is_dir"])
                name_s = colorize(e["name"] + ("/" if e["is_dir"] else ""), color)
                print(f"  {icon} {name_s}", end="")
                if (i + 1) % cols == 0:
                    print()
            print()

    def cmd_ll(self, args):
        """详细列表（同 ls -l）"""
        self.cmd_ls(["-l"] + args)

    def cmd_cd(self, args):
        """cd [path|..|~|bookmark]"""
        if not args:
            self.current_dir = os.path.expanduser("~")
            print(f"  → {self.current_dir}")
            return

        target = args[0]
        if target == "..":
            target = os.path.dirname(self.current_dir)
        elif target == "~":
            target = os.path.expanduser("~")
        elif target in self.bookmarks:
            target = self.bookmarks[target]
        else:
            target = self._resolve_path(target)

        if os.path.isdir(target):
            self.current_dir = os.path.abspath(target)
            print(f"  → {self.current_dir}")
        else:
            print(colorize(f"  目录不存在: {target}", C.RED))

    def cmd_pwd(self, args):
        print(self.current_dir)

    def cmd_back(self, args):
        """返回上级目录"""
        parent = os.path.dirname(self.current_dir)
        if parent and parent != self.current_dir:
            self.current_dir = parent
            print(f"  → {self.current_dir}")
        else:
            print(colorize("  已在根目录", C.YELLOW))

    def cmd_tree(self, args):
        """tree [-L depth] [path]"""
        max_depth = 3
        for i, a in enumerate(args):
            if a == "-L" and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except ValueError:
                    pass

        target = self.current_dir
        for a in args:
            if not a.startswith("-"):
                target = self._resolve_path(a)
                break

        print(colorize(f"  {os.path.basename(target) or target}/", C.BLUE + C.BOLD))
        self._print_tree(target, "", max_depth, 0)

    def _print_tree(self, path, prefix, max_depth, depth):
        if depth >= max_depth:
            return
        try:
            items = sorted(os.listdir(path),
                          key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
        except PermissionError:
            print(prefix + "  " + colorize("⚠ 无权限", C.RED))
            return

        items = [i for i in items if not i.startswith(".")]
        for idx, name in enumerate(items):
            full = os.path.join(path, name)
            is_last = idx == len(items) - 1
            branch = "└── " if is_last else "├── "
            icon = "📁" if os.path.isdir(full) else get_icon(name)
            color = get_color(name, os.path.isdir(full))
            name_s = colorize(name + ("/" if os.path.isdir(full) else ""), color)
            print(f"  {prefix}{branch}{icon} {name_s}")
            if os.path.isdir(full) and not is_last:
                extension = "    " if is_last else "│   "
                self._print_tree(full, prefix + extension, max_depth, depth + 1)

    # ==================== 文件操作 ====================

    def cmd_mkdir(self, args):
        """mkdir <name> [-p]"""
        if not args:
            print(colorize("  用法: mkdir <目录名> [-p]", C.RED))
            return
        name = args[0]
        parents = "-p" in args
        path = self._resolve_path(name)
        try:
            if parents:
                os.makedirs(path, exist_ok=True)
            else:
                os.mkdir(path)
            print(colorize(f"  ✔ 已创建: {path}", C.GREEN))
        except OSError as e:
            print(colorize(f"  ✖ 创建失败: {e}", C.RED))

    def cmd_touch(self, args):
        """touch <filename>"""
        if not args:
            print(colorize("  用法: touch <文件名>", C.RED))
            return
        for name in args:
            path = self._resolve_path(name)
            try:
                if os.path.exists(path):
                    os.utime(path, None)
                    print(f"  已更新时间戳: {name}")
                else:
                    with open(path, "w") as f:
                        pass
                    print(colorize(f"  ✔ 已创建: {name}", C.GREEN))
            except OSError as e:
                print(colorize(f"  ✖ 操作失败: {name} - {e}", C.RED))

    def cmd_rm(self, args):
        """rm <path> [-r] [-f]"""
        if not args:
            print(colorize("  用法: rm <路径> [-r 递归] [-f 强制]", C.RED))
            return
        recursive = "-r" in args or "-rf" in args or "-fr" in args
        force = "-f" in args or "-rf" in args or "-fr" in args

        targets = [a for a in args if not a.startswith("-")]
        for t in targets:
            path = self._resolve_path(t)
            if not os.path.exists(path):
                if not force:
                    print(colorize(f"  不存在: {t}", C.YELLOW))
                continue
            if os.path.isdir(path) and not recursive:
                print(colorize(f"  {t} 是目录，需加 -r", C.RED))
                continue
            if not force:
                confirm = safe_input(colorize(f"  确认删除 {t}? [y/N] ", C.YELLOW))
                if confirm and confirm.lower() != "y":
                    print("  已跳过")
                    continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(colorize(f"  ✔ 已删除: {t}", C.GREEN))
            except OSError as e:
                print(colorize(f"  ✖ 删除失败: {t} - {e}", C.RED))

    def cmd_cp(self, args):
        """cp <src> <dst> [-r]"""
        if len(args) < 2:
            print(colorize("  用法: cp <源> <目标> [-r]", C.RED))
            return
        recursive = "-r" in args
        src = self._resolve_path(args[0])
        dst = self._resolve_path(args[1])
        if not os.path.exists(src):
            print(colorize(f"  源不存在: {args[0]}", C.RED))
            return
        try:
            if os.path.isdir(src):
                if not recursive:
                    print(colorize("  源是目录，需加 -r", C.RED))
                    return
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            print(colorize(f"  ✔ 已复制: {args[0]} → {args[1]}", C.GREEN))
        except OSError as e:
            print(colorize(f"  ✖ 复制失败: {e}", C.RED))

    def cmd_mv(self, args):
        """mv <src> <dst>"""
        if len(args) < 2:
            print(colorize("  用法: mv <源> <目标>", C.RED))
            return
        src = self._resolve_path(args[0])
        dst = self._resolve_path(args[1])
        if not os.path.exists(src):
            print(colorize(f"  源不存在: {args[0]}", C.RED))
            return
        try:
            shutil.move(src, dst)
            print(colorize(f"  ✔ 已移动: {args[0]} → {args[1]}", C.GREEN))
        except OSError as e:
            print(colorize(f"  ✖ 移动失败: {e}", C.RED))

    def cmd_rename(self, args):
        """rename <old> <new>"""
        if len(args) < 2:
            print(colorize("  用法: rename <旧名> <新名>", C.RED))
            return
        old = self._resolve_path(args[0])
        new = self._resolve_path(args[1])
        if not os.path.exists(old):
            print(colorize(f"  不存在: {args[0]}", C.RED))
            return
        try:
            os.rename(old, new)
            print(colorize(f"  ✔ {args[0]} → {args[1]}", C.GREEN))
        except OSError as e:
            print(colorize(f"  ✖ 重命名失败: {e}", C.RED))

    # ==================== 查看内容 ====================

    def cmd_cat(self, args):
        """cat <file>"""
        if not args:
            print(colorize("  用法: cat <文件>", C.RED))
            return
        path = self._resolve_path(args[0])
        if not os.path.isfile(path):
            print(colorize(f"  不是文件: {args[0]}", C.RED))
            return
        try:
            size = os.path.getsize(path)
            if size > 5 * 1024 * 1024:
                print(colorize(f"  ⚠ 文件较大 ({format_size(size)})，仅显示前5MB", C.YELLOW))
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for i, line in enumerate(lines[:10000], 1):
                    print(f"{colorize(f'{i:>5}', C.GRAY)}  {line.rstrip()}")
                if len(lines) > 10000:
                    print(colorize(f"  ... 已截断，共 {len(lines)} 行", C.GRAY))
        except OSError as e:
            print(colorize(f"  ✖ 读取失败: {e}", C.RED))

    def cmd_head(self, args):
        """head <file> [-n lines]"""
        if not args:
            print(colorize("  用法: head <文件> [-n 行数]", C.RED))
            return
        n = 10
        for i, a in enumerate(args):
            if a == "-n" and i + 1 < len(args):
                try:
                    n = int(args[i + 1])
                except ValueError:
                    pass
        path = self._resolve_path(args[0])
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= n:
                        break
                    print(line.rstrip())
        except (OSError, ValueError) as e:
            print(colorize(f"  ✖ {e}", C.RED))

    def cmd_tail(self, args):
        """tail <file> [-n lines]"""
        if not args:
            print(colorize("  用法: tail <文件> [-n 行数]", C.RED))
            return
        n = 10
        for i, a in enumerate(args):
            if a == "-n" and i + 1 < len(args):
                try:
                    n = int(args[i + 1])
                except ValueError:
                    pass
        path = self._resolve_path(args[0])
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for line in lines[-n:]:
                    print(line.rstrip())
        except (OSError, ValueError) as e:
            print(colorize(f"  ✖ {e}", C.RED))

    def cmd_diff(self, args):
        """diff <file1> <file2>"""
        if len(args) < 2:
            print(colorize("  用法: diff <文件1> <文件2>", C.RED))
            return
        f1 = self._resolve_path(args[0])
        f2 = self._resolve_path(args[1])
        for f in [f1, f2]:
            if not os.path.isfile(f):
                print(colorize(f"  不是文件: {f}", C.RED))
                return

        h1 = self._file_hash(f1)
        h2 = self._file_hash(f2)
        print(f"  MD5:  {os.path.basename(f1):<20} {h1['md5']}")
        print(f"  MD5:  {os.path.basename(f2):<20} {h2['md5']}")
        print(f"  SHA256: {os.path.basename(f1):<18} {h1['sha256'][:32]}...")
        print(f"  SHA256: {os.path.basename(f2):<18} {h2['sha256'][:32]}...")

        if h1["md5"] == h2["md5"]:
            print(colorize("  ✔ 文件内容完全相同", C.GREEN))
            return

        try:
            with open(f1) as a, open(f2) as b:
                lines_a = a.readlines()
                lines_b = b.readlines()
        except OSError as e:
            print(colorize(f"  ✖ 读取失败: {e}", C.RED))
            return

        print(colorize("\n  --- 行级差异 (前50行) ---", C.YELLOW))
        max_lines = max(len(lines_a), len(lines_b))
        shown = 0
        for i in range(max_lines):
            la = lines_a[i].rstrip() if i < len(lines_a) else "<EOF>"
            lb = lines_b[i].rstrip() if i < len(lines_b) else "<EOF>"
            if la != lb:
                print(f"  {colorize(f'L{i+1}', C.GRAY)} {colorize('- '+la, C.RED)}")
                print(f"  {colorize(f'L{i+1}', C.GRAY)} {colorize('+ '+lb, C.GREEN)}")
                shown += 1
                if shown >= 50:
                    print(colorize("  ... 更多差异已省略", C.GRAY))
                    break

    def _file_hash(self, path):
        h_md5 = hashlib.md5()
        h_sha = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h_md5.update(chunk)
                    h_sha.update(chunk)
        except OSError:
            pass
        return {"md5": h_md5.hexdigest(), "sha256": h_sha.hexdigest()}

    # ==================== 搜索 & 信息 ====================

    def cmd_find(self, args):
        """find <pattern> [-t f|d] [-i] [path]"""
        if not args:
            print(colorize("  用法: find <模式> [-t f|d] [-i 忽略大小写] [路径]", C.RED))
            return

        pattern = args[0]
        target_type = "all"
        ignore_case = False
        search_path = self.current_dir

        for i, a in enumerate(args[1:], 1):
            if a == "-t" and i < len(args) - 1:
                target_type = args[i + 1]
            elif a == "-i":
                ignore_case = True
            elif not a.startswith("-"):
                search_path = self._resolve_path(a)

        if ignore_case:
            pattern_re = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        else:
            pattern_re = re.compile(fnmatch.translate(pattern))

        results = []
        for root, dirs, files in os.walk(search_path):
            for d in dirs:
                if target_type in ("all", "d") and pattern_re.match(d):
                    results.append(os.path.join(root, d))
            for f in files:
                if target_type in ("all", "f") and pattern_re.match(f):
                    results.append(os.path.join(root, f))

        if not results:
            print(colorize(f"  未找到匹配: {pattern}", C.YELLOW))
            return

        print(colorize(f"  找到 {len(results)} 个匹配项:", C.GREEN))
        for r in results[:200]:
            rel = os.path.relpath(r, self.current_dir)
            icon = "📁" if os.path.isdir(r) else get_icon(os.path.basename(r))
            color = get_color(os.path.basename(r), os.path.isdir(r))
            print(f"  {icon} {colorize(rel, color)}")
        if len(results) > 200:
            print(colorize(f"  ... 还有 {len(results)-200} 项未显示", C.GRAY))

    def cmd_info(self, args):
        """info <file|dir>"""
        if not args:
            print(colorize("  用法: info <文件或目录>", C.RED))
            return
        path = self._resolve_path(args[0])
        if not os.path.exists(path):
            print(colorize(f"  不存在: {args[0]}", C.RED))
            return

        st = os.stat(path)
        is_dir = os.path.isdir(path)
        print(colorize(f"\n  📋 信息: {os.path.basename(path)}", C.BOLD + C.BLUE))
        print(f"     路径:    {path}")
        print(f"     类型:    {'目录' if is_dir else '文件'}")
        print(f"     大小:    {format_size(st.st_size)} ({st.st_size} 字节)")
        print(f"     权限:    {format_perm(st.st_mode)}")
        if platform.system() != "Windows":
            print(f"     所有者:  {st.st_uid}")
            print(f"     组:      {st.st_gid}")
        print(f"     创建:    {format_time(st.st_ctime)}")
        print(f"     修改:    {format_time(st.st_mtime)}")
        print(f"     访问:    {format_time(st.st_atime)}")

        if not is_dir:
            h = self._file_hash(path)
            print(f"     MD5:     {h['md5']}")
            print(f"     SHA256:  {h['sha256']}")

    def cmd_du(self, args):
        """du [-d depth] [path]"""
        max_depth = 2
        for i, a in enumerate(args):
            if a == "-d" and i + 1 < len(args):
                try:
                    max_depth = int(args[i + 1])
                except ValueError:
                    pass

        target = self.current_dir
        for a in args:
            if not a.startswith("-"):
                target = self._resolve_path(a)
                break

        print(colorize(f"  📊 磁盘使用: {target}", C.BOLD))
        usage = self._calc_usage(target, max_depth, 0)
        if not usage:
            print("  (空目录)")
            return

        max_size = max(u["size"] for u in usage) or 1
        for entry in sorted(usage, key=lambda x: x["size"], reverse=True)[:30]:
            bar_len = int(entry["size"] / max_size * 30)
            bar = colorize("█" * bar_len, C.CYAN)
            icon = "📁" if entry["is_dir"] else get_icon(entry["name"])
            print(f"  {bar} {format_size(entry['size']):>10}  {icon} {entry['name']}")

    def _calc_usage(self, path, max_depth, depth):
        results = []
        if depth >= max_depth:
            return results
        try:
            items = os.listdir(path)
        except PermissionError:
            return results
        for item in items:
            full = os.path.join(path, item)
            try:
                if os.path.isdir(full):
                    size = self._dir_size(full)
                    results.append({"name": item, "size": size, "is_dir": True})
                    if depth + 1 < max_depth:
                        results.extend(self._calc_usage(full, max_depth, depth + 1))
                elif os.path.isfile(full):
                    results.append({"name": item, "size": os.path.getsize(full), "is_dir": False})
            except OSError:
                pass
        return results

    def _dir_size(self, path):
        total = 0
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def cmd_stats(self, args):
        """stats [path] — 统计目录中各类文件数量"""
        target = self.current_dir
        for a in args:
            if not a.startswith("-"):
                target = self._resolve_path(a)
                break

        if not os.path.isdir(target):
            print(colorize("  需指定目录", C.RED))
            return

        counts = defaultdict(int)
        total_size = defaultdict(int)
        for root, dirs, files in os.walk(target):
            for f in files:
                ext = f.rsplit(".", 1)[-1].lower() if "." in f else "(无扩展名)"
                size = 0
                try:
                    size = os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
                counts[ext] += 1
                total_size[ext] += size

        if not counts:
            print("  (空目录)")
            return

        print(colorize(f"  📊 文件统计: {target}", C.BOLD))
        print(f"  {'类型':<15} {'数量':>6}  {'总大小':>12}")
        print("  " + "-" * 38)
        for ext, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            color = COLOR_MAP.get(ext, C.RESET)
            print(f"  {color}{ext:<15}{C.RESET} {cnt:>6}  {format_size(total_size[ext]):>12}")

    # ==================== 压缩解压 ====================

    def cmd_zip(self, args):
        """zip <archive.zip> <source> [source2 ...]"""
        if len(args) < 2:
            print(colorize("  用法: zip <输出.zip> <源1> [源2 ...]", C.RED))
            return
        archive = self._resolve_path(args[0])
        sources = [self._resolve_path(a) for a in args[1:]]
        try:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for src in sources:
                    if not os.path.exists(src):
                        print(colorize(f"  跳过不存在: {src}", C.YELLOW))
                        continue
                    if os.path.isfile(src):
                        zf.write(src, os.path.basename(src))
                    else:
                        for root, dirs, files in os.walk(src):
                            for f in files:
                                full = os.path.join(root, f)
                                arcname = os.path.relpath(full, os.path.dirname(src))
                                zf.write(full, arcname)
            size = os.path.getsize(archive)
            print(colorize(f"  ✔ 已创建: {archive} ({format_size(size)})", C.GREEN))
        except OSError as e:
            print(colorize(f"  ✖ 压缩失败: {e}", C.RED))

    def cmd_unzip(self, args):
        """unzip <archive.zip> [-d dest]"""
        if not args:
            print(colorize("  用法: unzip <压缩包> [-d 目标目录]", C.RED))
            return
        archive = self._resolve_path(args[0])
        dest = self.current_dir
        for i, a in enumerate(args[1:], 1):
            if a == "-d" and i < len(args):
                dest = self._resolve_path(args[i + 1])

        if not os.path.isfile(archive):
            print(colorize(f"  文件不存在: {args[0]}", C.RED))
            return

        os.makedirs(dest, exist_ok=True)
        try:
            if archive.endswith(".zip"):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(dest)
            elif archive.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
                with tarfile.open(archive, "r:*") as tf:
                    tf.extractall(dest)
            else:
                print(colorize(f"  不支持的格式: {archive}", C.RED))
                return
            print(colorize(f"  ✔ 已解压到: {dest}", C.GREEN))
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
            print(colorize(f"  ✖ 解压失败: {e}", C.RED))

    def cmd_tar(self, args):
        """tar -c|-x <archive> [sources...] [-d dest]"""
        if len(args) < 2:
            print(colorize("  用法: tar -c <归档.tar.gz> <源...> | tar -x <归档> [-d 目标]", C.RED))
            return
        mode = args[0]
        archive = self._resolve_path(args[1])

        if mode in ("-c", "create"):
            sources = [self._resolve_path(a) for a in args[2:]]
            try:
                with tarfile.open(archive, "w:gz") as tf:
                    for src in sources:
                        if os.path.exists(src):
                            tf.add(src, arcname=os.path.basename(src))
                print(colorize(f"  ✔ 已创建: {archive}", C.GREEN))
            except OSError as e:
                print(colorize(f"  ✖ 打包失败: {e}", C.RED))
        elif mode in ("-x", "extract"):
            dest = self.current_dir
            for i, a in enumerate(args[2:], 2):
                if a == "-d" and i + 1 < len(args):
                    dest = self._resolve_path(args[i + 1])
            os.makedirs(dest, exist_ok=True)
            try:
                with tarfile.open(archive, "r:*") as tf:
                    tf.extractall(dest)
                print(colorize(f"  ✔ 已解压到: {dest}", C.GREEN))
            except (OSError, tarfile.TarError) as e:
                print(colorize(f"  ✖ 解压失败: {e}", C.RED))
        else:
            print(colorize(f"  未知模式: {mode}，使用 -c 或 -x", C.RED))

    # ==================== 批量操作 ====================

    def cmd_bulk_rename(self, args):
        """bulk-rename <pattern> <replacement> [path]"""
        if len(args) < 2:
            print(colorize("  用法: bulk-rename <正则模式> <替换字符串> [路径]", C.RED))
            print(colorize("  示例: bulk-rename 'img_(\\d+)' 'photo_\\1'", C.YELLOW))
            return

        pattern = re.compile(args[0])
        replacement = args[1]
        target_dir = self.current_dir
        for a in args[2:]:
            if not a.startswith("-"):
                target_dir = self._resolve_path(a)

        try:
            items = os.listdir(target_dir)
        except OSError as e:
            print(colorize(f"  ✖ {e}", C.RED))
            return

        matched = []
        for name in sorted(items):
            if pattern.search(name):
                new_name = pattern.sub(replacement, name)
                if new_name != name:
                    matched.append((name, new_name))

        if not matched:
            print(colorize("  没有匹配的文件", C.YELLOW))
            return

        print(colorize(f"  将重命名 {len(matched)} 个文件:", C.YELLOW))
        for old, new in matched:
            print(f"    {old} → {colorize(new, C.GREEN)}")

        confirm = safe_input(colorize("  确认执行? [y/N] ", C.YELLOW))
        if confirm and confirm.lower() == "y":
            for old, new in matched:
                src = os.path.join(target_dir, old)
                dst = os.path.join(target_dir, new)
                try:
                    os.rename(src, dst)
                except OSError as e:
                    print(colorize(f"  ✖ {old}: {e}", C.RED))
            print(colorize(f"  ✔ 完成 {len(matched)} 个重命名", C.GREEN))
        else:
            print("  已取消")

    def cmd_chmod(self, args):
        """chmod <mode> <file> (Unix only)"""
        if platform.system() == "Windows":
            print(colorize("  chmod 仅在 Unix/Linux/macOS 上可用", C.YELLOW))
            return
        if len(args) < 2:
            print(colorize("  用法: chmod <八进制权限> <文件>", C.RED))
            return
        try:
            mode = int(args[0], 8)
            path = self._resolve_path(args[1])
            os.chmod(path, mode)
            print(colorize(f"  ✔ 权限已设为 {args[0]}", C.GREEN))
        except (ValueError, OSError) as e:
            print(colorize(f"  ✖ {e}", C.RED))

    # ==================== open 命令 ====================

    def cmd_open(self, args):
        """
        open <file|dir|url> — 用系统默认程序打开
        等价于 macOS 'open' / Linux 'xdg-open' / Windows 'start'
        """
        if not args:
            print(colorize("  用法: open <文件|目录|URL>", C.RED))
            print(f"  示例:")
            print(f"    open report.pdf     # 用默认阅读器打开")
            print(f"    open .              # 打开当前目录")
            print(f"    open https://github.com  # 用浏览器打开")
            return

        target = self._resolve_path(args[0])

        # 特殊处理 "." 为当前目录
        if args[0] == ".":
            target = self.current_dir

        try:
            if platform.system() == "Windows":
                if os.path.exists(target) or os.path.isdir(target):
                    os.startfile(target)
                else:
                    # 可能是 URL
                    os.startfile(args[0])
            elif platform.system() == "Darwin":
                subprocess.run(["open", target], check=True)
            else:
                subprocess.run(["xdg-open", target], check=True)
            print(colorize(f"  ✔ 已打开: {args[0]}", C.GREEN))
        except Exception as e:
            print(colorize(f"  ✖ 打开失败: {e}", C.RED))

    # ==================== edit / nano 命令 ====================

    def cmd_edit(self, args):
        """
        edit|nano <file> — 内嵌 nano 风格文本编辑器
        支持输入、删除、方向键移动、保存、查找等功能
        """
        if not args:
            print(colorize("  用法: edit <文件>", C.RED))
            print(colorize("  快捷键: Ctrl+S 保存 | Ctrl+X 退出 | Ctrl+W 查找", C.YELLOW))
            print(colorize("          Ctrl+G 跳行 | Tab 缩进 | Esc 帮助", C.YELLOW))
            return

        # --help 显示编辑器帮助
        if args[0] == "--help" or args[0] == "-h":
            print(colorize("\n  📝  Winux 内置编辑器 — 快捷键", C.BOLD + C.BLUE))
            print("  " + "═" * 45)
            print("   Ctrl+S   保存文件")
            print("   Ctrl+X   退出（有修改时提示保存）")
            print("   Ctrl+W   查找文本")
            print("   Ctrl+G   跳转到指定行")
            print("   Ctrl+A   跳到文件末尾")
            print("   Tab      插入 4 空格缩进")
            print("   Esc      显示此帮助")
            print("   方向键   移动光标")
            print("   Home/End 光标到行首/行尾")
            print("   Delete   删除光标后字符")
            print("   Backspc  删除光标前字符")
            print("   Enter    换行")
            print("  " + "═" * 45)
            return

        path = self._resolve_path(args[0])

        # 如果文件不存在，创建空文件
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    pass
                print(colorize(f"  ✔ 已创建新文件: {path}", C.GREEN))
            except OSError as e:
                print(colorize(f"  ✖ 无法创建文件: {e}", C.RED))
                return

        # 二进制文件检测
        try:
            with open(path, "rb") as f:
                chunk = f.read(512)
                if b"\x00" in chunk:
                    print(colorize("  ⚠ 检测到二进制文件，拒绝编辑", C.YELLOW))
                    print(f"  提示: 用 'open {args[0]}' 用外部程序打开")
                    return
        except OSError:
            pass

        # 文件太大警告
        try:
            size = os.path.getsize(path)
            if size > 10 * 1024 * 1024:
                print(colorize(f"  ⚠ 文件较大 ({format_size(size)})，建议用外部编辑器", C.YELLOW))
                confirm = safe_input(colorize("  仍要编辑? [y/N] ", C.YELLOW))
                if not confirm or confirm.lower() != "y":
                    return
        except OSError:
            pass

        print(colorize("  📝 进入编辑器... (按任意键继续)", C.CYAN))
        msvcrt.getch()

        # 启动编辑器
        editor = NanoEditor(path)
        editor.run()

        # 恢复终端
        sys.stdout.write("\033[2J\033[H")
        print(colorize(f"  ← 已退出编辑器: {path}", C.CYAN))

    # ==================== apt 包管理器 ====================

    def cmd_apt(self, args):
        """
        apt <子命令> <包名> — Windows 包管理器前端
        自动检测 winget / choco / scoop 并转换命令
        """
        if not args:
            self._apt_help()
            return

        # --help
        if args[0] in ("--help", "-h", "help"):
            self._apt_help()
            return

        if platform.system() != "Windows":
            print(colorize("  apt 命令仅支持 Windows 系统", C.YELLOW))
            print("  Linux/macOS 请直接使用系统自带的包管理器")
            return

        if not self.apt_backend:
            print(colorize("  ⚠ 未检测到可用的包管理器", C.RED))
            print("  请安装以下任一工具后重试:")
            print("    • winget  (Microsoft Store 安装 '应用安装程序')")
            print("    • choco   (https://chocolatey.org)")
            print("    • scoop   (https://scoop.sh)")
            return

        action = args[0].lower()
        packages = args[1:] if len(args) > 1 else []

        # 构建命令
        cmd = self._build_apt_command(action, packages)
        if cmd is None:
            print(colorize(f"  未知操作: {action}", C.RED))
            self._apt_help()
            return

        # 显示将要执行的命令
        display_cmd = " ".join(cmd) if isinstance(cmd, list) else cmd
        print(colorize(f"  ▷ 执行: {display_cmd}", C.CYAN))
        print(colorize(f"  ▷ 后端: {self.apt_backend}", C.GRAY))

        try:
            if isinstance(cmd, list):
                result = subprocess.run(cmd, check=False)
            else:
                # shell 命令
                result = subprocess.run(cmd, shell=True, check=False)
            if result.returncode == 0:
                print(colorize(f"  ✔ 操作完成", C.GREEN))
            else:
                print(colorize(f"  ⚠ 命令返回码: {result.returncode}", C.YELLOW))
        except FileNotFoundError:
            print(colorize(f"  ✖ {self.apt_backend} 不可用，请检查安装", C.RED))
            # 尝试重新检测
            self.apt_backend = self._detect_apt_backend()
        except Exception as e:
            print(colorize(f"  ✖ 执行失败: {e}", C.RED))

    def _build_apt_command(self, action, packages):
        """将 apt 子命令转换为对应后端的命令"""
        backend = self.apt_backend

        if backend == "winget":
            return self._winget_cmd(action, packages)
        elif backend == "choco":
            return self._choco_cmd(action, packages)
        elif backend == "scoop":
            return self._scoop_cmd(action, packages)
        return None

    def _winget_cmd(self, action, packages):
        if action in ("install", "i"):
            if not packages:
                return ["winget", "install", "--help"]
            return ["winget", "install", "--exact", "--silent"] + packages
        elif action in ("remove", "uninstall", "rm"):
            if not packages:
                return ["winget", "uninstall", "--help"]
            return ["winget", "uninstall", "--exact", "--silent"] + packages
        elif action in ("update",):
            return ["winget", "source", "update"]
        elif action in ("upgrade", "update-all"):
            return ["winget", "upgrade", "--all"]
        elif action in ("search", "s"):
            if not packages:
                return ["winget", "search"]
            return ["winget", "search"] + packages
        elif action in ("list", "ls"):
            return ["winget", "list"]
        elif action in ("show", "info"):
            if not packages:
                return ["winget", "show", "--help"]
            return ["winget", "show"] + packages
        elif action in ("autoremove",):
            print(colorize("  ℹ Windows 无 autoremove 概念，请手动卸载不需要的包", C.GRAY))
            return None
        elif action in ("clean",):
            print(colorize("  ℹ winget 缓存清理: %LOCALAPPDATA%\\Packages\\Microsoft.DesktopAppInstaller", C.GRAY))
            return None
        return None

    def _choco_cmd(self, action, packages):
        if action in ("install", "i"):
            if not packages:
                return ["choco", "install", "--help"]
            return ["choco", "install", "-y"] + packages
        elif action in ("remove", "uninstall", "rm"):
            if not packages:
                return ["choco", "uninstall", "--help"]
            return ["choco", "uninstall", "-y"] + packages
        elif action in ("update",):
            return ["choco", "upgrade", "all", "-y"]
        elif action in ("upgrade", "update-all"):
            return ["choco", "upgrade", "all", "-y"]
        elif action in ("search", "s"):
            if not packages:
                return ["choco", "search"]
            return ["choco", "search"] + packages
        elif action in ("list", "ls"):
            return ["choco", "list", "-y", "--local-only"]
        elif action in ("show", "info"):
            if not packages:
                return ["choco", "info"]
            return ["choco", "info"] + packages
        elif action in ("autoremove",):
            print(colorize("  ℹ choco 无 autoremove，请手动 choco uninstall <包>", C.GRAY))
            return None
        elif action in ("clean",):
            return ["choco", "clean", "-y"]
        return None

    def _scoop_cmd(self, action, packages):
        if action in ("install", "i"):
            if not packages:
                return ["scoop", "install", "--help"]
            return ["scoop", "install"] + packages
        elif action in ("remove", "uninstall", "rm"):
            if not packages:
                return ["scoop", "uninstall", "--help"]
            return ["scoop", "uninstall"] + packages
        elif action in ("update",):
            return ["scoop", "update", "*"]
        elif action in ("upgrade", "update-all"):
            return ["scoop", "update", "*"]
        elif action in ("search", "s"):
            if not packages:
                return ["scoop", "search"]
            return ["scoop", "search"] + packages
        elif action in ("list", "ls"):
            return ["scoop", "list"]
        elif action in ("show", "info"):
            if not packages:
                return ["scoop", "info", "--help"]
            return ["scoop", "info"] + packages
        elif action in ("autoremove",):
            print(colorize("  ℹ scoop 无 autoremove，请手动 scoop uninstall <包>", C.GRAY))
            return None
        elif action in ("clean",):
            return ["scoop", "cache", "rm", "*"]
        return None

    def _apt_help(self):
        print(colorize("\n  📦  Winux apt — 包管理器前端", C.BOLD + C.BLUE))
        print("  " + "═" * 50)
        print(f"  当前后端: {colorize(self.apt_backend or '未检测到', C.GREEN if self.apt_backend else C.RED)}")
        print()
        print("  用法: apt <子命令> [包名...]")
        print()
        print("  子命令:")
        print("    install <包>    安装软件包")
        print("    remove  <包>    卸载软件包")
        print("    update          更新软件源/缓存")
        print("    upgrade         升级所有已安装的包")
        print("    search  <关键字> 搜索软件包")
        print("    list            列出已安装的包")
        print("    show    <包>    显示包详细信息")
        print("    autoremove      移除不再需要的依赖")
        print("    clean           清理缓存")
        print()
        print("  示例:")
        print("    apt install git python nodejs")
        print("    apt search vscode")
        print("    apt remove old-package")
        print()
        print("  支持的后端: winget > choco > scoop")
        print("  " + "═" * 50)

    # ==================== 书签 ====================

    def cmd_bookmark(self, args):
        """bookmark [add <name> <path>] [del <name>] [list] [go <name>]"""
        if not args or args[0] == "list":
            if not self.bookmarks:
                print("  (无书签)")
            else:
                print(colorize("  📑 书签列表:", C.BOLD))
                for name, path in self.bookmarks.items():
                    print(f"    {colorize(name, C.CYAN)} → {path}")
            return

        action = args[0]
        if action == "add":
            if len(args) < 3:
                name = args[1] if len(args) > 1 else os.path.basename(self.current_dir)
                self.bookmarks[name] = self.current_dir
                print(colorize(f"  ✔ 书签 '{name}' → {self.current_dir}", C.GREEN))
            else:
                name = args[1]
                path = self._resolve_path(args[2])
                self.bookmarks[name] = os.path.abspath(path)
                print(colorize(f"  ✔ 书签 '{name}' → {path}", C.GREEN))
            self._save_bookmarks()
        elif action in ("del", "remove"):
            name = args[1] if len(args) > 1 else ""
            if name in self.bookmarks:
                del self.bookmarks[name]
                self._save_bookmarks()
                print(colorize(f"  ✔ 已删除书签: {name}", C.GREEN))
            else:
                print(colorize(f"  书签不存在: {name}", C.YELLOW))
        elif action in ("go", "open"):
            name = args[1] if len(args) > 1 else ""
            if name in self.bookmarks:
                self.current_dir = self.bookmarks[name]
                print(f"  → {self.current_dir}")
            else:
                print(colorize(f"  书签不存在: {name}", C.YELLOW))
        else:
            print(colorize(f"  未知操作: {action}", C.RED))

    # ==================== 历史 & 清屏 ====================

    def cmd_history(self, args):
        if not self.history:
            print("  (无历史)")
            return
        for i, cmd in enumerate(self.history[-20:], 1):
            print(f"  {colorize(f'{i:>3}', C.GRAY)}  {cmd}")

    def cmd_clear(self, args):
        if platform.system() == "Windows":
            os.system("cls")
        else:
            os.system("clear")

    # ==================== 帮助 & 退出 ====================

    def cmd_help(self, args):
        help_text = f"""
{colorize('🐧 Winux v' + self.VERSION + ' - 命令帮助', C.BOLD + C.BLUE)}
{'═' * 52}

  {colorize('导航', C.YELLOW)}
    ls [-l 详细] [-a 含隐藏] [-s 按大小] [路径]   列出目录
    ll [路径]                                    详细列表
    cd <路径|..|~|书签名>                         切换目录
    pwd                                          显示当前路径
    back                                         返回上级
    tree [-L 深度] [路径]                         目录树

  {colorize('文件操作', C.YELLOW)}
    mkdir <名> [-p]                              创建目录
    touch <文件>                                 创建/更新文件
    cp <源> <目标> [-r]                          复制
    mv <源> <目标>                               移动/重命名
    rename <旧> <新>                             重命名
    rm <路径> [-r 递归] [-f 强制]                 删除

  {colorize('查看 & 编辑', C.YELLOW)}
    cat <文件>                                   查看全文
    head <文件> [-n 行数]                        查看头部
    tail <文件> [-n 行数]                        查看尾部
    diff <文件1> <文件2>                         文件差异
    edit|nano <文件>                             内嵌文本编辑器
    open <文件|目录|URL>                         系统默认程序打开

  {colorize('搜索 & 分析', C.YELLOW)}
    find <模式> [-t f|d] [-i] [路径]             模式搜索
    info <文件>                                  文件详细信息
    du [-d 深度] [路径]                          磁盘使用
    stats [路径]                                 文件类型统计

  {colorize('压缩解压', C.YELLOW)}
    zip <输出.zip> <源...>                       压缩
    unzip <压缩包> [-d 目标]                     解压
    tar -c <归档> <源...>                        打包 tar.gz
    tar -x <归档> [-d 目标]                      解包

  {colorize('批量 & 高级', C.YELLOW)}
    bulk-rename <正则> <替换> [路径]             批量重命名
    chmod <权限> <文件>                          Unix 权限

  {colorize('包管理 (apt)', C.YELLOW)}
    apt install <包>                             安装软件
    apt remove  <包>                             卸载软件
    apt search  <关键字>                         搜索软件
    apt list                                     列出已安装
    apt update                                   更新源
    apt upgrade                                  升级全部

  {colorize('书签', C.YELLOW)}
    bookmark list                                列出书签
    bookmark add <名> [路径]                     添加书签
    bookmark del <名>                            删除书签
    bookmark go  <名>                            跳转书签

  {colorize('其他', C.YELLOW)}
    history                                     命令历史
    clear / cls                                 清屏
    help                                        显示帮助
    quit / exit                                 退出

  {colorize('编辑器快捷键 (edit/nano)', C.MAGENTA)}
    Ctrl+S 保存    Ctrl+X 退出    Ctrl+W 查找
    Ctrl+G 跳行    Tab 缩进      Esc 帮助
{'═' * 52}
"""
        print(help_text)

    def cmd_quit(self, args):
        print(colorize("\n  再见！👋  —  Made with ❤️ on Windows", C.CYAN))
        sys.exit(0)

    # ==================== 工具方法 ====================

    def _resolve_path(self, path):
        """解析路径：支持 ~ 和相对路径"""
        if path.startswith("~"):
            path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.join(self.current_dir, path)
        return os.path.normpath(path)


# ============================================================
#  入口
# ============================================================
def main():
    start_dir = sys.argv[1] if len(sys.argv) > 1 else None
    app = Winux(start_dir)
    app.run()

if __name__ == "__main__":
    main()
