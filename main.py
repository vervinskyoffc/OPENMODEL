import sqlite3, os, time, sys, requests, platform, json, io, subprocess, re, shutil, threading, textwrap, shlex, queue, signal, difflib
from pathlib import Path
from datetime import datetime

HOST_OS = platform.system() or "Unknown"
IS_WINDOWS = HOST_OS == "Windows"
IS_LINUX = HOST_OS == "Linux"
IS_MACOS = HOST_OS == "Darwin"

# ─── Fix Windows Console UTF-8 & ANSI ─────────────────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

if IS_WINDOWS:
    _VT_FLAGS = 0x0001 | 0x0002 | 0x0004
    _INVALID_HANDLE = -1
    try:
        import ctypes
        _kernel32 = ctypes.windll.kernel32
        for _hid in (-10, -11, -12):
            _h = _kernel32.GetStdHandle(_hid)
            if _h == 0 or ctypes.c_long(_h).value == _INVALID_HANDLE:
                continue
            _m = ctypes.c_ulong(0)
            if _kernel32.GetConsoleMode(_h, ctypes.byref(_m)):
                _kernel32.SetConsoleMode(_h, _m.value | _VT_FLAGS)
    except Exception:
        pass

# ─── prompt_toolkit for autocompletion & inputs ──────────────────────────────
try:
    from prompt_toolkit import prompt as _pt_prompt
    from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    _HAS_PT = True
    _COMMANDS = [
        '/model', 'model', '/new', 'new', '/clear', 'clear', '/cls', 'cls',
        '/help', 'help', '/tab', 'tab', '/history', 'history', '/config', 'config',
        '/reset', 'reset', '/reset config', 'reset config',
        '/exit', 'exit', '/quit', 'quit',
        '/read', 'read file', '/modify', 'modify'
    ]
    _completer = WordCompleter(_COMMANDS, ignore_case=True, sentence=True)
    _input_history = InMemoryHistory()
except ImportError:
    _HAS_PT = False
    _completer = None
    _input_history = None

# ─── ANSI Palette ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
ITALIC = "\033[3m"

def rgb(r, g, b): return f"\033[38;2;{r};{g};{b}m"

C_WHITE   = rgb(241, 245, 249)
C_GRAY    = rgb(148, 163, 184)
C_DIM_C   = rgb(71,  85,  105)
C_ACCENT  = rgb(56,  189, 248)    # Sky blue
C_ACCENT2 = rgb(168, 85,  247)    # Purple
C_GREEN   = rgb(34,  197, 94)     # Emerald
C_RED     = rgb(239, 68,  68)     # Rose red
C_YELLOW  = rgb(245, 158, 11)     # Amber
C_TEAL    = rgb(20,  184, 166)

BG_CODE   = "\033[48;2;15;23;42m"
BG_SELECT = "\033[48;2;30;41;59m"
VERSION   = "v3.3-fixed"

# ─── Helpers ──────────────────────────────────────────────────────────────────
def tw():
    return max(60, shutil.get_terminal_size((100, 30)).columns)

def strip_ansi(s):
    return re.sub(r'\033\[[0-9;]*[mK]', '', s)

def vis_len(s):
    return len(strip_ansi(s))

def ellipsize(text, max_len):
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max(0, max_len - 1)] + '…' if max_len > 1 else '…'

def os_label():
    if IS_LINUX:   return "Linux"
    if IS_MACOS:   return "macOS"
    if IS_WINDOWS: return "Windows"
    return HOST_OS

def shell_label():
    if IS_WINDOWS: return "cmd.exe"
    shell = os.environ.get("SHELL") or "/bin/sh"
    return os.path.basename(shell) or "sh"

def center_print(text, width=None):
    w   = width or tw()
    pad = max(0, (w - vis_len(text)) // 2)
    print(' ' * pad + text)

def clear_screen():
    if IS_WINDOWS:
        os.system('cls')
    else:
        sys.stdout.write('\033[H\033[2J\033[3J')
        sys.stdout.flush()

def clean_content(text):
    text = text.strip()
    m = re.match(r'^```[a-zA-Z0-9_-]*\n(.*?)```$', text, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return text

def clean_path(path):
    path = path.strip(" \t\r\n\"'`")
    return re.sub(r'[*?<>|]', '', path)

# ─── Stdin Flush & Key Reader ─────────────────────────────────────────────────
def flush_stdin():
    try:
        if IS_WINDOWS:
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass

def get_key():
    """Reads a single keypress without buffering blocks."""
    if IS_WINDOWS:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            ch2 = msvcrt.getwch()
            if ch2 == 'H': return 'UP'
            if ch2 == 'P': return 'DOWN'
            if ch2 == 'K': return 'LEFT'
            if ch2 == 'M': return 'RIGHT'
            return ''
        if ch in ('\r', '\n'): return 'ENTER'
        if ch == '\t': return 'TAB'
        if ch == '\x1b': return 'ESC'
        if ch in ('\x08', '\x7f'): return 'BACKSPACE'
        return ch
    else:
        import termios, tty
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                import select
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r:
                    ch2 = sys.stdin.read(1)
                    if ch2 == '[':
                        ch3 = sys.stdin.read(1)
                        if ch3 == 'A': return 'UP'
                        if ch3 == 'B': return 'DOWN'
                        if ch3 == 'C': return 'RIGHT'
                        if ch3 == 'D': return 'LEFT'
                return 'ESC'
            if ch in ('\n', '\r'): return 'ENTER'
            if ch == '\t': return 'TAB'
            if ch in ('\x7f', '\x08'): return 'BACKSPACE'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# ─── Logo ─────────────────────────────────────────────────────────────────────
LOGO = [
    "  ██████╗ ██████╗ ███████╗███╗   ██╗███╗   ███╗ ██████╗ ██████╗ ███████╗██╗     ",
    " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║████╗ ████║██╔═══██╗██╔══██╗██╔════╝██║     ",
    " ██║   ██║██████╔╝█████╗  ██╔██╗ ██║██╔████╔██║██║   ██║██║  ██║█████╗  ██║     ",
    " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║╚██╔╝██║██║   ██║██║  ██║██╔══╝  ██║     ",
    " ╚██████╔╝██║     ███████╗██║ ╚████║██║ ╚═╝ ██║╚██████╔╝██████╔╝███████╗███████╗",
    "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝╚══════╝",
]

def print_logo():
    W = tw()
    print()
    bw = len(LOGO[0])
    if W >= bw + 2:
        for i, line in enumerate(LOGO):
            ratio = i / max(len(LOGO) - 1, 1)
            r = int(56  * (1 - ratio) + 168 * ratio)
            g = int(189 * (1 - ratio) + 85  * ratio)
            b = int(248 * (1 - ratio) + 247 * ratio)
            pad = (W - bw) // 2
            print(' ' * pad + rgb(r, g, b) + BOLD + line + RESET)
    else:
        center_print(BOLD + C_ACCENT + '◆ OPENMODEL ◆' + RESET)
    print()

# ─── Home Screen ──────────────────────────────────────────────────────────────
def _pw(): return min(78, max(40, tw() - 6))
def _pp(): return max(0, (tw() - _pw()) // 2)

def _panel_row(content='', border_col=C_ACCENT):
    pw  = _pw()
    sp  = ' ' * _pp()
    bar = f"{border_col}│{RESET}"
    inner_len = pw - 2
    vis = vis_len(content)
    pad = ' ' * max(0, inner_len - vis)
    print(f"{sp}{bar} {content}{pad}{bar}")

def render_home(model_name_val, api_ok):
    clear_screen()
    print_logo()
    pw = _pw()
    sp = ' ' * _pp()
    top = f"{sp}{C_ACCENT}╭{'─' * pw}╮{RESET}"
    bot = f"{sp}{C_ACCENT}╰{'─' * pw}╯{RESET}"
    mid = f"{sp}{C_DIM_C}├{'─' * pw}┤{RESET}"

    api_str = f"{C_GREEN}● online{RESET}" if api_ok else f"{C_RED}● offline{RESET}"
    prov_str = "Google AI Studio" if is_google_key(api_key) else "OpenRouter AI"
    cwd_str = ellipsize(os.getcwd().replace(str(Path.home()), '~'), pw - 20)

    print(top)
    _panel_row(f"{BOLD}{C_WHITE}WORKSPACE INTERFACE{RESET}  {DIM}{C_GRAY}{VERSION}{RESET}")
    print(mid)
    _panel_row(f"{DIM}{C_GRAY}PROVIDER {RESET} {C_ACCENT2}{prov_str}{RESET}")
    _panel_row(f"{DIM}{C_GRAY}MODEL    {RESET} {BOLD}{C_ACCENT}{ellipsize(model_name_val, pw - 18)}{RESET}")
    _panel_row(f"{DIM}{C_GRAY}ENV      {RESET} {C_TEAL}{os_label()}{RESET} {DIM}({shell_label()}){RESET}")
    _panel_row(f"{DIM}{C_GRAY}STATUS   {RESET} {api_str}")
    _panel_row(f"{DIM}{C_GRAY}WORKDIR  {RESET} {C_WHITE}{cwd_str}{RESET}")
    print(bot)

    hints = (f"{DIM}{C_GRAY}Команды: {C_ACCENT}/model{C_GRAY} (смена модели) • "
             f"{C_ACCENT}/help{C_GRAY} (помощь) • {C_ACCENT}/reset{C_GRAY} (сброс настроек) • {C_ACCENT}/new{C_GRAY} (новый чат){RESET}")
    center_print(hints)
    print()
    sys.stdout.flush()

# ─── Robust Interactive Model Selector ────────────────────────────────────────
def interactive_model_selector(models_list: list[dict], current_model: str) -> str:
    """Zero-flicker model selector supporting both Arrows and Direct Number selection."""
    if not models_list:
        models_list = fetch_fallback_google_models()

    flush_stdin()
    selected_idx = 0
    for idx, m in enumerate(models_list):
        if m['id'].lower() == (current_model or '').lower():
            selected_idx = idx
            break

    page_size = min(9, len(models_list))
    filter_query = ""

    sys.stdout.write("\033[?25l")  # Hide cursor
    sys.stdout.flush()
    try:
        while True:
            filtered = [
                m for m in models_list
                if filter_query.lower() in m['id'].lower() or filter_query.lower() in m.get('name', '').lower()
            ]
            if not filtered:
                filtered = models_list

            selected_idx = max(0, min(selected_idx, len(filtered) - 1))
            start_idx = max(0, min(selected_idx - page_size // 2, len(filtered) - page_size))
            start_idx = max(0, start_idx)
            end_idx = min(len(filtered), start_idx + page_size)
            visible_items = filtered[start_idx:end_idx]

            box_w = min(76, tw() - 6)
            sp = "   "

            # Construct the complete UI frame in memory to avoid screen tears
            lines = []
            lines.append("")
            w_title = tw()
            pad_t = max(0, (w_title - vis_len("ВЫБОР МОДЕЛИ ИИ")) // 2)
            lines.append(' ' * pad_t + BOLD + C_ACCENT + "ВЫБОР МОДЕЛИ ИИ" + RESET)
            sub = "Стрелки ↑/↓ или Цифры (1-9) | Выбор: ENTER/TAB | Отмена: ESC"
            pad_s = max(0, (w_title - vis_len(sub)) // 2)
            lines.append(' ' * pad_s + DIM + C_GRAY + sub + RESET)
            lines.append("")

            lines.append(f"{sp}{C_ACCENT}╭{'─' * box_w}╮{RESET}")
            if filter_query:
                q_vis = f" Поиск: {C_YELLOW}{filter_query}█{RESET}"
                pad_q = " " * max(0, box_w - vis_len(q_vis))
                lines.append(f"{sp}{C_ACCENT}│{RESET}{q_vis}{pad_q}{C_ACCENT}│{RESET}")
                lines.append(f"{sp}{C_ACCENT}├{'─' * box_w}┤{RESET}")

            for i, item in enumerate(visible_items):
                actual_i = start_idx + i
                is_cur = (actual_i == selected_idx)
                mid = item['id']
                desc = ellipsize(item.get('desc', ''), 28)
                num_tag = f"[{actual_i + 1}]"

                if is_cur:
                    left_tag = f" {C_ACCENT}❯{RESET} {C_YELLOW}{num_tag:<4}{RESET} {BOLD}{C_WHITE}{mid:<30}{RESET}"
                    desc_tag = f"{C_TEAL}{desc}{RESET}"
                else:
                    left_tag = f"   {DIM}{C_GRAY}{num_tag:<4}{RESET} {C_GRAY}{mid:<30}{RESET}"
                    desc_tag = f"{DIM}{C_GRAY}{desc}{RESET}"

                content = f"{left_tag} {desc_tag}"
                pad = " " * max(0, box_w - vis_len(content))
                lines.append(f"{sp}{C_ACCENT}│{RESET}{content}{pad}{C_ACCENT}│{RESET}")

            footer = f" Модели {start_idx+1}-{end_idx} из {len(filtered)} "
            f_pad = "─" * max(0, box_w - len(footer) - 2)
            lines.append(f"{sp}{C_ACCENT}├{f_pad}{C_DIM_C}{footer}{C_ACCENT}─┤{RESET}")
            lines.append(f"{sp}{C_ACCENT}╰{'─' * box_w}╯{RESET}")
            lines.append("")

            # Clear and print whole frame synchronously
            clear_screen()
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()

            key = get_key()
            if key == 'UP':
                selected_idx = (selected_idx - 1) % len(filtered)
            elif key == 'DOWN':
                selected_idx = (selected_idx + 1) % len(filtered)
            elif key in ('ENTER', 'TAB'):
                flush_stdin()
                return filtered[selected_idx]['id']
            elif key == 'ESC':
                flush_stdin()
                return current_model or filtered[0]['id']
            elif key == 'BACKSPACE':
                if filter_query:
                    filter_query = filter_query[:-1]
            elif key.isdigit():
                val = int(key)
                if 1 <= val <= len(filtered):
                    flush_stdin()
                    return filtered[val - 1]['id']
            elif len(key) == 1 and key.isprintable():
                filter_query += key
    finally:
        sys.stdout.write("\033[?25h")  # Ensure cursor is restored
        sys.stdout.flush()

# ─── Unified Diff Visualizer ──────────────────────────────────────────────────
def display_file_diff(file_path: str, old_content: str, new_content: str, is_new=False):
    """Prints a clean Git-style unified diff in the terminal."""
    old_lines = old_content.splitlines(keepends=True) if old_content else []
    new_lines = new_content.splitlines(keepends=True) if new_content else []
    
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=2
    ))

    added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
    removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

    action = "Создан файл" if is_new else "Изменён файл"
    badge_color = C_GREEN if is_new else C_YELLOW

    W = min(tw() - 6, 88)
    print()
    print(f"  {badge_color}●{RESET} {BOLD}{C_WHITE}{action}:{RESET} {C_ACCENT}{file_path}{RESET} "
          f"{DIM}({C_GREEN}+{added}{RESET}{DIM}, {C_RED}-{removed}{RESET}{DIM} строк){RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}")

    if not diff:
        print(f"    {DIM}{C_GRAY}(Без изменений в тексте){RESET}")
        print()
        return

    for line in diff[:60]:
        line_clean = line.rstrip('\r\n')
        if line.startswith('+++') or line.startswith('---'):
            print(f"    {BOLD}{C_GRAY}{line_clean}{RESET}")
        elif line.startswith('@@'):
            print(f"    {C_TEAL}{line_clean}{RESET}")
        elif line.startswith('+'):
            print(f"    {C_GREEN}+ {line_clean[1:]}{RESET}")
        elif line.startswith('-'):
            print(f"    {C_RED}- {line_clean[1:]}{RESET}")
        else:
            print(f"    {DIM}{C_GRAY}  {line_clean}{RESET}")

    if len(diff) > 60:
        print(f"    {DIM}{C_YELLOW}... diff обрезан ({len(diff)-60} строк ещё) ...{RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}\n")

# ─── Conversation Input ───────────────────────────────────────────────────────
def read_input(nickname_str='You'):
    now = datetime.now().strftime('%H:%M')
    print()
    _msg_header(nickname_str, C_ACCENT, now)
    prompt_str = f'  {C_ACCENT}❯{RESET} {C_WHITE}'
    
    try:
        if _HAS_PT:
            user_input = _pt_prompt(
                _PT_ANSI(prompt_str),
                completer=_completer,
                history=_input_history,
                multiline=False
            )
        else:
            sys.stdout.write(f"  {C_ACCENT}❯{RESET} ")
            sys.stdout.flush()
            user_input = input()
    except (EOFError, KeyboardInterrupt):
        return ''
    
    sys.stdout.write(RESET)
    return user_input.strip()

# ─── Spinner ──────────────────────────────────────────────────────────────────
def format_elapsed(seconds):
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

class Spinner:
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self, label='Thinking'):
        self.label = label
        self._stop = threading.Event()
        self._thread = None
        self._start_time = 0
        self.streamed_text = ''

    def update_text(self, text):
        clean = re.sub(r'\[(NEW_FILE|EDIT_FILE|MODIFIED_FILE)[\s:\]].*?\[/\1\]', '[Обновление файлов...]', text, flags=re.DOTALL)
        self.streamed_text = clean

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            f = self.FRAMES[i % len(self.FRAMES)]
            elapsed = int(time.time() - self._start_time)
            td_str = format_elapsed(elapsed)
            
            snippet = self.streamed_text.replace('\n', ' ')
            snippet = re.sub(r'\x1b\[[0-9;]*m', '', snippet).strip()
            
            w = tw()
            prefix = f'\r  {C_ACCENT2}{f}{RESET}  {DIM}{C_GRAY}{self.label} [{td_str}] '
            max_snip = max(0, w - vis_len(prefix) - 6)
            if len(snippet) > max_snip and max_snip > 3:
                snippet = "..." + snippet[-(max_snip-3):]
            elif len(snippet) > max_snip:
                snippet = ""
                
            line = prefix + f"{C_GRAY}{snippet}{RESET}"
            sys.stdout.write(line + ' ' * max(0, w - vis_len(line)) + '\r')
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def start(self, reset_timer=True):
        if reset_timer:
            self._start_time = time.time()
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        sys.stdout.write('\r' + ' ' * tw() + '\r')
        sys.stdout.flush()

class RequestCancelled(Exception):
    pass

# ─── Formatting Chat Output ───────────────────────────────────────────────────
def _msg_header(label, color, ts=None):
    W = tw()
    ts_str = f'  {DIM}{C_GRAY}{ts}{RESET}' if ts else ''
    hdr = f'  {color}{BOLD}{label}{RESET}{ts_str}'
    hv  = vis_len(hdr)
    print(hdr + '  ' + C_DIM_C + '─' * max(0, W - hv - 4) + RESET)

def _ai_header(model_name_str):
    print()
    _msg_header(f'AI  ·  {model_name_str}', C_ACCENT2)
    print()

def strip_code_tags_for_chat(text: str) -> str:
    def rep_new(m):
        path = m.group(1).strip()
        return f"\n> 📁 **Создан файл:** `{path}`\n"
    def rep_edit(m):
        path = m.group(1).strip()
        return f"\n> 📝 **Внесены правки в:** `{path}`\n"
    def rep_cmd(m):
        cmd = m.group(1).strip()
        return f"\n> ⚡ **Команда:** `{cmd}`\n"

    clean = re.sub(r'\[NEW_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/NEW_FILE\]|\Z)', rep_new, text, flags=re.DOTALL)
    clean = re.sub(r'\[EDIT_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/EDIT_FILE\]|\Z)', rep_edit, clean, flags=re.DOTALL)
    clean = re.sub(r'\[CMD\](.*?)\[/CMD\]', rep_cmd, clean, flags=re.DOTALL)
    return clean

def render_inline(line):
    line = re.sub(r'\*\*(.+?)\*\*', lambda m: BOLD + C_WHITE + m.group(1) + RESET + C_WHITE, line)
    line = re.sub(r'\*(.+?)\*',     lambda m: ITALIC + m.group(1) + RESET + C_WHITE, line)
    line = re.sub(r'`([^`]+)`',     lambda m: BG_CODE + C_TEAL + ' ' + m.group(1) + ' ' + RESET + C_WHITE, line)
    return line

def print_ai_response(text):
    clean_text = strip_code_tags_for_chat(text)
    W     = tw()
    width = min(W - 8, 96)
    lines = clean_text.split('\n')
    in_code, lang, code_buf = False, '', []
    in_think = False

    def flush_code():
        nonlocal code_buf, lang
        if not code_buf: return
        cw = width
        hdr = f'  {lang if lang else "code"} '
        print('    ' + BG_CODE + C_TEAL + BOLD + hdr + ' ' * max(0, cw - len(hdr) + 2) + RESET)
        for cl in code_buf:
            print('    ' + BG_CODE + C_WHITE + '  ' + cl + ' ' * max(0, cw - len(cl)) + RESET)
        print('    ' + BG_CODE + ' ' * (cw + 2) + RESET)
        code_buf.clear()
        lang = ''

    i = 0
    while i < len(lines):
        line = lines[i]
        
        has_think_start = '<think>' in line
        has_think_end   = '</think>' in line
        if has_think_start:
            in_think = True
            line = line.replace('<think>', '')
        if has_think_end:
            in_think = False
            line = line.replace('</think>', '')
        if (has_think_start or has_think_end) and not line.strip():
            i += 1
            continue
            
        tc = DIM + C_GRAY if in_think else C_WHITE

        if line.startswith('```'):
            if not in_code:
                in_code = True
                lang = line[3:].strip()
            else:
                in_code = False
                flush_code()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        h = re.match(r'^(#{1,3})\s+(.*)', line)
        if h:
            col = [C_ACCENT, C_ACCENT2, C_TEAL][min(len(h.group(1)) - 1, 2)]
            print(f'\n    {BOLD}{col}{h.group(2)}{RESET}')
            i += 1
            continue
        if re.match(r'^[-─]{3,}$', line.strip()):
            print('    ' + C_DIM_C + '─' * width + RESET)
            i += 1
            continue
        bul = re.match(r'^(\s*)([-*•]|\d+\.)\s+(.*)', line)
        if bul:
            indent = len(bul.group(1))
            marker = bul.group(2)
            rest   = bul.group(3)
            pfx = f'    {"  " * (indent // 2)}{C_ACCENT}▸{RESET} '
            pv = vis_len(pfx)
            for j, wl in enumerate(textwrap.wrap(rest, width - pv + 4) or ['']):
                print((pfx if j == 0 else ' ' * pv) + tc + render_inline(wl) + RESET)
            i += 1
            continue
        if not line.strip():
            print()
        else:
            for row in textwrap.wrap(line, width) or ['']:
                print(f'    {tc}{render_inline(row)}{RESET}')
        i += 1
    if in_code and code_buf:
        flush_code()

# ─── Streaming Engine ─────────────────────────────────────────────────────────
def confirm_cancel_request():
    try:
        ans = input(f'\n  {C_YELLOW}Отменить запрос? (y/N):{RESET}  ').strip().lower()
    except KeyboardInterrupt:
        return True
    return ans in ('y', 'yes', 'д', 'да')

def print_ai_stream(generator, mdl, control=None):
    spinner = Spinner('Генерация')
    full = ''
    start_time = time.time()
    token_queue = queue.Queue()
    done = object()
    cancel_event = threading.Event()
    sigint_event = threading.Event()
    old_sigint = None
    sigint_installed = False

    def sigint_handler(_signum, _frame):
        sigint_event.set()

    def install_sigint():
        nonlocal old_sigint, sigint_installed
        if threading.current_thread() is not threading.main_thread() or sigint_installed:
            return
        old_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, sigint_handler)
        sigint_installed = True

    def restore_sigint():
        nonlocal sigint_installed
        if threading.current_thread() is threading.main_thread() and sigint_installed:
            signal.signal(signal.SIGINT, old_sigint)
            sigint_installed = False

    def close_active_response():
        if control is not None:
            control['cancelled'] = True
            resp = control.get('response')
            if resp is not None:
                try: resp.close()
                except Exception: pass

    def stream_worker():
        try:
            for token in generator:
                if cancel_event.is_set(): break
                token_queue.put(('token', token))
        except BaseException as e:
            if not cancel_event.is_set():
                token_queue.put(('error', e))
        finally:
            token_queue.put((done, None))

    def handle_cancel():
        spinner.stop()
        restore_sigint()
        try:
            should_cancel = confirm_cancel_request()
        finally:
            install_sigint()

        if should_cancel:
            cancel_event.set()
            close_active_response()
            worker.join(timeout=1)
            print(f'\n  {DIM}{C_GRAY}[Отменено]{RESET}\n')
            raise RequestCancelled()

        sigint_event.clear()
        print(f'  {DIM}{C_GRAY}Продолжение...{RESET}')
        spinner.start(reset_timer=False)

    worker = threading.Thread(target=stream_worker, daemon=True)
    worker.start()
    install_sigint()
    spinner.start()

    try:
        while True:
            try:
                while True:
                    if sigint_event.is_set(): raise KeyboardInterrupt()
                    try:
                        kind, value = token_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if sigint_event.is_set(): raise KeyboardInterrupt()
                    if kind is done: break
                    if kind == 'error': raise value

                    full += value
                    spinner.update_text(full)
                break
            except KeyboardInterrupt:
                handle_cancel()
                continue
    finally:
        restore_sigint()
        spinner.stop()

    elapsed = int(time.time() - start_time)
    if full.strip():
        _ai_header(mdl)
        print_ai_response(full)
        print()
        td_str = format_elapsed(elapsed)
        print(f'    {DIM}{C_GRAY}Выполнено за {td_str}{RESET}\n')
    return full

# ─── Config Database ──────────────────────────────────────────────────────────
USERDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userdata")
os.makedirs(USERDATA_DIR, exist_ok=True)

CONFIG_DB = os.path.join(USERDATA_DIR, 'config.db')
conn = sqlite3.connect(CONFIG_DB)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY,
                api_key TEXT,
                model TEXT,
                nickname TEXT,
                system_prompt TEXT DEFAULT ''
            )""")
conn.commit()

# ─── Model Fetching & Fallbacks ───────────────────────────────────────────────
def is_google_key(k: str) -> bool:
    if not k: return False
    k = k.strip()
    return k.startswith(('AQ.', 'AQ', 'AIza')) or (not k.startswith('sk-or-') and len(k) >= 28)

def fetch_fallback_google_models():
    return [
        {'id': 'gemini-2.0-flash',      'desc': 'Флагман скорости и качества (рекомендуется)'},
        {'id': 'gemini-2.0-flash-lite', 'desc': 'Максимально быстрая и легкая'},
        {'id': 'gemini-1.5-flash',      'desc': 'Высокая пропускная способность'},
        {'id': 'gemini-1.5-pro',        'desc': 'Сложные задачи и большой контекст'},
    ]

def fetch_google_models(key: str) -> list[dict]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        r = requests.get(url, headers={'x-goog-api-key': key}, timeout=4)
        if r.status_code == 200:
            models = []
            for m in r.json().get('models', []):
                methods = m.get('supportedGenerationMethods', [])
                name = m.get('name', '').replace('models/', '')
                low = name.lower()
                
                if any(x in low for x in ('tts', 'audio', 'image', 'embedding', 'aqa', 'realtime', 'imagen')):
                    continue

                if 'generateContent' in methods and 'gemini' in low:
                    desc = m.get('description', '').split('.')[0]
                    models.append({
                        'id': name,
                        'name': m.get('displayName', name),
                        'desc': desc
                    })
            if models:
                return models
    except Exception:
        pass
    return fetch_fallback_google_models()

def fetch_openrouter_models() -> list[dict]:
    return [
        {'id': 'openai/gpt-4o-mini',               'desc': 'Быстрая и умная модель'},
        {'id': 'openai/gpt-4o',                    'desc': 'Флагман OpenAI'},
        {'id': 'anthropic/claude-3.5-sonnet',      'desc': 'Лучшая для программирования'},
        {'id': 'deepseek/deepseek-r1',              'desc': 'Продвинутое рассуждение'},
        {'id': 'meta-llama/llama-3.3-70b-instruct','desc': 'Мощная Open-source модель'},
    ]

def select_model_menu(current=None):
    if is_google_key(api_key):
        models = fetch_google_models(api_key)
    else:
        models = fetch_openrouter_models()
    return interactive_model_selector(models, current or model_name)

# ─── Setup Wizard ─────────────────────────────────────────────────────────────
def setup_wizard():
    clear_screen()
    print_logo()
    center_print(BOLD + C_WHITE + "ПЕРВОНАЧАЛЬНАЯ НАСТРОЙКА" + RESET)
    center_print(DIM + C_GRAY + "Поддерживает Google AI Studio и OpenRouter" + RESET)
    print()

    def ask(prompt_text, default=None):
        dflt = f'{DIM}{C_GRAY} [{default}]{RESET}' if default else ''
        sys.stdout.write(f'  {C_ACCENT}❯{RESET} {C_WHITE}{prompt_text}{RESET}{dflt}: ')
        sys.stdout.flush()
        val = input().strip()
        return val if val else (default or '')

    flush_stdin()
    api_k = ask('Введите ваш API Ключ')
    while not api_k:
        api_k = ask('Введите ваш API Ключ')

    if is_google_key(api_k):
        models_available = fetch_google_models(api_k)
        selected_model = interactive_model_selector(models_available, 'gemini-2.0-flash')
    else:
        models_available = fetch_openrouter_models()
        selected_model = interactive_model_selector(models_available, 'openai/gpt-4o-mini')

    clear_screen()
    print_logo()
    flush_stdin()
    nick = ask('Ваш никнейм', default='Dev')

    c.execute('DELETE FROM config WHERE id=1')
    c.execute('INSERT INTO config (id, api_key, model, nickname, system_prompt) VALUES (1,?,?,?,?)',
              (api_k, selected_model, nick, ''))
    conn.commit()
    return api_k, selected_model, nick, ''

# ─── Load Config ──────────────────────────────────────────────────────────────
c.execute('SELECT api_key, model, nickname, system_prompt FROM config WHERE id=1')
row = c.fetchone()
if row:
    api_key, model_name, nickname, system_prompt = row
else:
    api_key, model_name, nickname, system_prompt = setup_wizard()

# ─── Chat DB ──────────────────────────────────────────────────────────────────
CHATS_DB = os.path.join(USERDATA_DIR, 'chats.db')
chat_conn = sqlite3.connect(CHATS_DB)
chat_c = chat_conn.cursor()
chat_c.execute("""CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_input TEXT,
                    ai_response TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )""")
chat_conn.commit()

# ─── API Check ────────────────────────────────────────────────────────────────
def check_api():
    import socket
    host = 'generativelanguage.googleapis.com' if is_google_key(api_key) else 'openrouter.ai'
    try:
        socket.setdefaulttimeout(3)
        socket.gethostbyname(host)
        return True
    except:
        return False

API_AVAILABLE = check_api()

# ─── System Prompt ────────────────────────────────────────────────────────────
def shell_guidance():
    if IS_WINDOWS:
        return "Shell: Windows CMD. Use `dir`, `type`. Paths with spaces must be quoted."
    return "Shell: POSIX. Use `ls`, `cat`, `grep`, `find`, `python3`."

def default_system_prompt():
    return (
        "You are OPENMODEL — an Autonomous Lead Software Engineer and CLI agent.\n\n"
        "### RULES FOR FILE CREATION & EDITING:\n"
        "1. NEW FILE:\n"
        "[NEW_FILE: path/to/file.ext]\n"
        "RAW_FILE_CONTENT\n"
        "[/NEW_FILE]\n\n"
        "2. EDIT EXISTING FILE:\n"
        "[EDIT_FILE: path/to/file.ext]\n"
        "RAW_FULL_NEW_FILE_CONTENT\n"
        "[/EDIT_FILE]\n\n"
        "3. RUN COMMANDS:\n"
        "[CMD]command[/CMD]\n\n"
        "4. DO NOT print the code in normal chat markdown when using [NEW_FILE] or [EDIT_FILE]. "
        "The CLI parses your tags and displays a beautiful unified git diff (+ / -) to the user. "
        "Provide only concise explanations outside tags.\n"
        f"5. {shell_guidance()}"
    )

DEFAULT_SYS = default_system_prompt()

def runtime_system_context():
    return f"CURRENT WORKDIR: {os.getcwd()}\nPLATFORM: {os_label()} ({shell_label()})\nDESKTOP: {get_desktop()}"

# ─── Stream Providers ─────────────────────────────────────────────────────────
def stream_openrouter(messages, extra_system=None, control=None):
    if not API_AVAILABLE:
        yield '[API ERROR] OpenRouter недоступен.'
        return
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://openrouter.ai'
    }
    sys_msg = (extra_system or system_prompt or DEFAULT_SYS) + f"\n\n{runtime_system_context()}"
    payload = {
        'model': model_name,
        'messages': [{'role': 'system', 'content': sys_msg}] + messages,
        'stream': True,
        'include_reasoning': True
    }
    try:
        in_reasoning = False
        with requests.post('https://openrouter.ai/api/v1/chat/completions',
                           headers=headers, json=payload, stream=True, timeout=60) as resp:
            if control is not None: control['response'] = resp
            resp.encoding = 'utf-8'
            if resp.status_code != 200:
                yield f'[API ERROR] HTTP {resp.status_code}: {resp.text[:250]}'
                return
            for line in resp.iter_lines(decode_unicode=True):
                if control and control.get('cancelled'): return
                if not line or not line.startswith('data: '): continue
                chunk_str = line[6:].strip()
                if chunk_str == '[DONE]': break
                try:
                    data = json.loads(chunk_str)
                    delta = data['choices'][0].get('delta', {})
                    r_tok = delta.get('reasoning', '')
                    c_tok = delta.get('content', '')
                    if r_tok:
                        if not in_reasoning:
                            yield '<think>\n'; in_reasoning = True
                        yield r_tok
                    if c_tok:
                        if in_reasoning:
                            yield '\n</think>\n'; in_reasoning = False
                        yield c_tok
                except Exception:
                    continue
        if in_reasoning:
            yield '\n</think>\n'
    except Exception as e:
        if control and control.get('cancelled'): return
        yield f'[API ERROR] {e}'

def stream_google_gemini(messages, extra_system=None, control=None):
    if not API_AVAILABLE:
        yield '[API ERROR] Google AI Studio недоступен.'
        return
    sys_msg = (extra_system or system_prompt or DEFAULT_SYS) + f"\n\n{runtime_system_context()}"
    contents = []
    for m in messages:
        contents.append({
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}]
        })

    payload = {
        "contents": contents,
        "system_instruction": {"parts": [{"text": sys_msg}]}
    }
    target = model_name.replace('models/', '')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{target}:streamGenerateContent?alt=sse&key={api_key}"
    
    try:
        in_reasoning = False
        with requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, stream=True, timeout=60) as resp:
            if control is not None: control['response'] = resp
            resp.encoding = 'utf-8'
            if resp.status_code != 200:
                yield f'[API ERROR] HTTP {resp.status_code}: {resp.text[:300]}'
                return
            for line in resp.iter_lines(decode_unicode=True):
                if control and control.get('cancelled'): return
                if not line or not line.startswith('data: '): continue
                raw = line[6:].strip()
                if not raw or raw == '[DONE]': continue
                try:
                    data = json.loads(raw)
                    parts = data.get('candidates', [])[0].get('content', {}).get('parts', [])
                    for p in parts:
                        text_val = p.get('text', '')
                        if not text_val: continue
                        if p.get('thought', False):
                            if not in_reasoning:
                                yield '<think>\n'; in_reasoning = True
                            yield text_val
                        else:
                            if in_reasoning:
                                yield '\n</think>\n'; in_reasoning = False
                            yield text_val
                except Exception:
                    continue
        if in_reasoning:
            yield '\n</think>\n'
    except Exception as e:
        if control and control.get('cancelled'): return
        yield f'[API ERROR] {e}'

def stream_ai(messages, extra_system=None, control=None):
    if is_google_key(api_key):
        return stream_google_gemini(messages, extra_system=extra_system, control=control)
    return stream_openrouter(messages, extra_system=extra_system, control=control)

# ─── Execution Helpers ────────────────────────────────────────────────────────
def get_desktop():
    if IS_WINDOWS:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
            d, _ = winreg.QueryValueEx(k, 'Desktop')
            winreg.CloseKey(k)
            if os.path.exists(d): return d
        except: pass
        return os.path.expandvars(r'%USERPROFILE%\Desktop')
    return str(Path.home() / 'Desktop')

def expand_special_path(p):
    p = str(p).replace('%DESKTOP%', get_desktop()).replace('$DESKTOP', get_desktop())
    return os.path.expandvars(os.path.expanduser(p)).strip(' "\'')

def resolve_path(path, base_dir=None):
    clean = clean_path(expand_special_path(path))
    return clean if os.path.isabs(clean) else os.path.join(base_dir or os.getcwd(), clean)

def execute_command(cmd):
    cmd = expand_special_path(cmd)
    if cmd.strip().lower().startswith('cd '):
        target = resolve_path(cmd.strip()[3:])
        try:
            os.chdir(target)
            return f"[Каталог изменен на {os.getcwd()}]"
        except Exception as e:
            return f"[ERROR] {e}"
    try:
        env = os.environ.copy()
        env['DESKTOP'] = get_desktop()
        if IS_WINDOWS:
            full_cmd = f'chcp 65001 >nul 2>&1 & {cmd}'
            r = subprocess.run(['cmd.exe', '/c', full_cmd], capture_output=True, text=True, timeout=45, encoding='utf-8', errors='replace', env=env)
        else:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=45, encoding='utf-8', errors='replace', env=env)
        out = (r.stdout + ('\n' + r.stderr if r.stderr else '')).strip()
        return out or '[Успешно выполнено]'
    except subprocess.TimeoutExpired:
        return '[ERROR] Таймаут команды (45s)'
    except Exception as e:
        return f'[ERROR] {e}'

def confirm_exec(cmd):
    print()
    print(f'  {C_YELLOW}⚡ OPENMODEL запрашивает выполнение команды:{RESET}')
    print(f'    {BG_CODE}{C_TEAL}  $ {cmd}  {RESET}')
    print()
    ans = input(f'  {C_YELLOW}Разрешить? (y/N):{RESET}  ').strip().lower()
    return ans in ('y', 'yes', 'д', 'да')

def is_read_only(cmd):
    verb = cmd.strip().split()[0].lower() if cmd.strip() else ''
    safe = {'cat', 'ls', 'dir', 'type', 'grep', 'find', 'git', 'pwd', 'head', 'tail', 'stat', 'which'}
    return verb in safe and '>' not in cmd and '|' not in cmd

# ─── Help & Config Screens ────────────────────────────────────────────────────
def show_help():
    W = min(tw() - 4, 80)
    print()
    print(f"  {BOLD}{C_ACCENT}СПИСОК КОМАНД{RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}")
    cmds = [
        ('/model, model',          'Выбор модели стрелками или цифрами 1-9'),
        ('/new, new',              'Начать новый диалог (очистить память)'),
        ('/clear, /cls, cls',      'Очистить терминал и показать инфо-панель'),
        ('/reset, reset config',   'Сбросить настройки и запустить мастер'),
        ('/history',               'Показать историю последних диалогов'),
        ('/config',                'Показать текущие настройки'),
        ('/exit, quit',            'Выход из программы'),
    ]
    for k, v in cmds:
        print(f"  {C_ACCENT}{k:<24}{RESET} {C_WHITE}{v}{RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}\n")

def show_config():
    W = min(tw() - 4, 80)
    print()
    print(f"  {BOLD}{C_ACCENT}КОНФИГУРАЦИЯ{RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}")
    prov = "Google AI Studio" if is_google_key(api_key) else "OpenRouter AI"
    print(f"  {C_GRAY}Провайдер:{RESET}     {C_WHITE}{prov}{RESET}")
    print(f"  {C_GRAY}Модель:{RESET}        {BOLD}{C_ACCENT}{model_name}{RESET}")
    print(f"  {C_GRAY}Никнейм:{RESET}       {C_WHITE}{nickname}{RESET}")
    print(f"  {C_GRAY}Рабочая папка:{RESET} {C_WHITE}{os.getcwd()}{RESET}")
    print(f"  {C_GRAY}API Статус:{RESET}    {C_GREEN if API_AVAILABLE else C_RED}● {'Онлайн' if API_AVAILABLE else 'Офлайн'}{RESET}")
    print(f"  {C_DIM_C}{'─' * W}{RESET}\n")

# ─── Main Execution Loop ──────────────────────────────────────────────────────
def main():
    global model_name, api_key, nickname, system_prompt, API_AVAILABLE

    conversation: list[dict] = []
    render_home(model_name, API_AVAILABLE)

    while True:
        try:
            user_input = read_input(nickname)
        except (EOFError, KeyboardInterrupt):
            print(f'\n\n  {DIM}{C_GRAY}Сессия завершена.{RESET}\n')
            break

        if not user_input:
            continue

        raw = user_input.strip()
        low = raw.lower()
        cmd_token = low.lstrip('/')

        # ── 1. Intercept Local System Commands ────────────────────────────────
        if cmd_token in ('exit', 'quit', 'q', ':q'):
            print(f'\n  {DIM}{C_GRAY}До свидания!{RESET}\n')
            break

        if cmd_token in ('cls', 'clear'):
            render_home(model_name, API_AVAILABLE)
            continue

        if cmd_token == 'new':
            conversation.clear()
            render_home(model_name, API_AVAILABLE)
            print(f"  {C_GREEN}✓ Память диалога очищена.{RESET}\n")
            continue

        if cmd_token in ('help', 'tab', '?'):
            show_help()
            continue

        if cmd_token == 'config':
            show_config()
            continue

        if cmd_token in ('reset', 'reset config'):
            c.execute('DELETE FROM config WHERE id=1')
            conn.commit()
            print(f"\n  {C_YELLOW}✓ Конфигурация сброшена.{RESET}")
            time.sleep(0.8)
            api_key, model_name, nickname, system_prompt = setup_wizard()
            conversation.clear()
            API_AVAILABLE = check_api()
            render_home(model_name, API_AVAILABLE)
            continue

        if cmd_token == 'history':
            chat_c.execute('SELECT user_input, ai_response, timestamp FROM chats ORDER BY id DESC LIMIT 5')
            rows = chat_c.fetchall()
            print()
            for u, a, ts in reversed(rows):
                print(f"  {DIM}{C_GRAY}[{ts}]{RESET} {C_ACCENT}{nickname}:{RESET} {u[:80]}")
                print(f"  {C_ACCENT2}AI:{RESET} {DIM}{strip_ansi(a or '')[:120].replace(chr(10), ' ')}{RESET}\n")
            continue

        if cmd_token == 'model' or cmd_token.startswith('model '):
            arg = raw.split(' ', 1)[1].strip() if ' ' in raw else ''
            if not arg:
                new_mdl = select_model_menu(model_name)
                if new_mdl and new_mdl != model_name:
                    model_name = new_mdl
                    c.execute('UPDATE config SET model=? WHERE id=1', (model_name,))
                    conn.commit()
                render_home(model_name, API_AVAILABLE)
                print(f"  {C_GREEN}✓ Модель изменена на:{RESET} {BOLD}{C_ACCENT}{model_name}{RESET}\n")
            else:
                model_name = arg
                c.execute('UPDATE config SET model=? WHERE id=1', (model_name,))
                conn.commit()
                print(f"\n  {C_GREEN}✓ Модель установлена:{RESET} {BOLD}{C_ACCENT}{model_name}{RESET}\n")
            continue

        if cmd_token.startswith('cd '):
            new_dir = resolve_path(raw[3:])
            try:
                os.chdir(new_dir)
                print(f'\n  {C_GREEN}✓ Текущая папка:{RESET} {C_ACCENT}{os.getcwd()}{RESET}\n')
            except Exception as e:
                print(f'\n  {C_RED}✗ Ошибка смены папки: {e}{RESET}\n')
            continue

        # ── 2. AI Request Loop (Only non-command messages reach here) ─────────
        conversation.append({'role': 'user', 'content': raw})

        for _ in range(5):
            control = {}
            try:
                full = print_ai_stream(stream_ai(conversation, control=control), model_name, control)
            except RequestCancelled:
                conversation.pop()
                break
            except KeyboardInterrupt:
                print(f'\n  {C_GRAY}[Прервано]{RESET}\n')
                conversation.pop()
                break

            if not full:
                break

            conversation.append({'role': 'assistant', 'content': full})

            # Handle File Creations
            for match in re.finditer(r'\[NEW_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/NEW_FILE\]|\Z)', full, re.DOTALL):
                f_path = resolve_path(match.group(1).strip())
                new_c = clean_content(match.group(2))
                old_c = ""
                if os.path.exists(f_path):
                    try: old_c = open(f_path, 'r', encoding='utf-8', errors='replace').read()
                    except: pass
                os.makedirs(os.path.dirname(f_path) or '.', exist_ok=True)
                with open(f_path, 'w', encoding='utf-8') as f:
                    f.write(new_c + '\n')
                display_file_diff(f_path, old_c, new_c, is_new=not bool(old_c))

            # Handle File Modifications
            for match in re.finditer(r'\[EDIT_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/EDIT_FILE\]|\Z)', full, re.DOTALL):
                f_path = resolve_path(match.group(1).strip())
                new_c = clean_content(match.group(2))
                old_c = ""
                if os.path.exists(f_path):
                    try: old_c = open(f_path, 'r', encoding='utf-8', errors='replace').read()
                    except: pass
                os.makedirs(os.path.dirname(f_path) or '.', exist_ok=True)
                with open(f_path, 'w', encoding='utf-8') as f:
                    f.write(new_c + '\n')
                display_file_diff(f_path, old_c, new_c, is_new=False)

            # Handle Commands
            cmds = [m.strip() for m in re.findall(r'\[CMD\](.*?)\[/CMD\]', full, re.DOTALL) if m.strip()]
            if not cmds:
                chat_c.execute('INSERT INTO chats (user_input, ai_response) VALUES (?,?)', (raw, full))
                chat_conn.commit()
                break

            cmd_outputs = []
            for cmd in cmds:
                if is_read_only(cmd) or confirm_exec(cmd):
                    out = execute_command(cmd)
                    print(f"    {C_GRAY}{out[:300]}{RESET}\n")
                    cmd_outputs.append(f"Результат `{cmd}`:\n```\n{out}\n```")
                else:
                    cmd_outputs.append(f"Команда `{cmd}` отклонена пользователем.")

            if cmd_outputs:
                conversation.append({'role': 'user', 'content': "Результаты команд:\n" + "\n\n".join(cmd_outputs)})
            else:
                break

    conn.close()
    chat_conn.close()

if __name__ == '__main__':
    main()