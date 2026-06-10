import sqlite3, os, time, sys, requests, platform, json, io, subprocess, re, shutil, threading, textwrap, shlex, queue, signal
from pathlib import Path
from datetime import datetime

HOST_OS = platform.system() or "Unknown"
IS_WINDOWS = HOST_OS == "Windows"
IS_LINUX = HOST_OS == "Linux"
IS_MACOS = HOST_OS == "Darwin"

# ─── Optional: prompt_toolkit for proper input wrap/indent ────────────────────
try:
    from prompt_toolkit import prompt as _pt_prompt
    from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

# ─── Windows UTF-8 + VT100 ANSI fix ─────────────────────────────────────────
if IS_WINDOWS:
    # Step 1: Enable VT processing FIRST, before any stdout wrapping.
    # ENABLE_PROCESSED_OUTPUT            = 0x0001
    # ENABLE_WRAP_AT_EOL_OUTPUT          = 0x0002
    # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    _VT_FLAGS = 0x0001 | 0x0002 | 0x0004
    _INVALID_HANDLE = -1  # INVALID_HANDLE_VALUE as signed int
    try:
        import ctypes
        _kernel32 = ctypes.windll.kernel32
        for _hid in (-10, -11, -12):   # stdin, stdout, stderr handles
            _h = _kernel32.GetStdHandle(_hid)
            # Skip invalid handles (may happen when launched via shortcut/UAC)
            if _h == 0 or ctypes.c_long(_h).value == _INVALID_HANDLE:
                continue
            _m = ctypes.c_ulong(0)
            if _kernel32.GetConsoleMode(_h, ctypes.byref(_m)):
                _kernel32.SetConsoleMode(_h, _m.value | _VT_FLAGS)
    except Exception:
        pass

    # Step 2: Flush before wrapping so no buffered bytes are lost.
    sys.stdout.flush()
    sys.stderr.flush()
    # Step 3: Wrap stdout/stderr for UTF-8 AFTER VT is enabled.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── ANSI helpers ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
ITALIC = "\033[3m"

def rgb(r, g, b):    return f"\033[38;2;{r};{g};{b}m"
def bg_rgb(r, g, b): return f"\033[48;2;{r};{g};{b}m"

C_WHITE   = rgb(226, 232, 240)
C_GRAY    = rgb(148, 163, 184)
C_DIM_C   = rgb(55,  65,  81)
C_ACCENT  = rgb(56,  189, 248)
C_ACCENT2 = rgb(167, 139, 250)
C_GREEN   = rgb(34,  197, 94)
C_RED     = rgb(248, 113, 113)
C_YELLOW  = rgb(250, 204, 21)
C_ORANGE  = rgb(251, 146, 60)
C_TEAL    = rgb(45,  212, 191)
C_BLUE    = rgb(96,  165, 250)

BG_PANEL  = bg_rgb(20, 22, 26)
BG_STATUS = bg_rgb(13, 17, 23)
BG_CODE   = bg_rgb(9,  25, 29)

VERSION = "v2.2-linux"

# ─── Terminal helpers ──────────────────────────────────────────────────────────
def tw():
    return shutil.get_terminal_size((100, 30)).columns

def th():
    return shutil.get_terminal_size((100, 30)).lines

def strip_ansi(s):
    return re.sub(r'\033\[[^m]*m', '', s)

def vis_len(s):
    return len(strip_ansi(s))

def ellipsize(text, max_len):
    text = str(text)
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return '…'
    return '…' + text[-(max_len - 1):]

def os_label():
    if IS_LINUX:
        return "Linux"
    if IS_MACOS:
        return "macOS"
    if IS_WINDOWS:
        return "Windows"
    return HOST_OS

def shell_label():
    if IS_WINDOWS:
        return "cmd.exe"
    shell = os.environ.get("SHELL") or "/bin/sh"
    return os.path.basename(shell) or "sh"

def center_print(text, width=None):
    w   = width or tw()
    pad = max(0, (w - vis_len(text)) // 2)
    print(' ' * pad + text)

def clear_screen():
    # ANSI: erase entire screen + scrollback, then move cursor to top-left
    # This works reliably in Windows Terminal, cmd, and Linux/macOS
    sys.stdout.write('\033[3J\033[2J\033[H')
    sys.stdout.flush()

def clean_content(text):
    text = text.strip()
    m = re.match(r'^```[a-zA-Z0-9]*\n(.*?)```$', text, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return text

def clean_path(path):
    path = path.strip(" \t\r\n\"'`")
    # Remove characters that commonly leak from generated placeholder paths.
    return re.sub(r'[*?<>|]', '', path)

def is_dummy_path(p):
    if not p: return True
    p = p.replace('\\', '/').strip().lower()
    return p in ('path/to/file', 'path/relative/to/project', 'path', 'path/to/cmd', 'to cmd', 'path/to/file.ext', 'filename.ext', 'path/to')


# ─── Logo ─────────────────────────────────────────────────────────────────────
LOGO_BIG = [
    " ██████╗ ██████╗ ███████╗███╗   ██╗███╗   ███╗ ██████╗ ██████╗ ███████╗██╗     ",
    "██╔═══██╗██╔══██╗██╔════╝████╗  ██║████╗ ████║██╔═══██╗██╔══██╗██╔════╝██║     ",
    "██║   ██║██████╔╝█████╗  ██╔██╗ ██║██╔████╔██║██║   ██║██║  ██║█████╗  ██║     ",
    "██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║╚██╔╝██║██║   ██║██║  ██║██╔══╝  ██║     ",
    "╚██████╔╝██║     ███████╗██║ ╚████║██║ ╚═╝ ██║╚██████╔╝██████╔╝███████╗███████╗",
    " ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝╚══════╝",
]

LOGO_MID = [
    " ██████╗  ███╗   ███╗ ",
    "██╔═══██╗ █████╗ ███║",
    "██║   ██║ ██╔████╔██║",
    "██║   ██║ ██║╚██╔╝██║",
    "╚██████╔╝ ██║ ╚═╝ ██║",
    " ╚═════╝  ╚═╝     ╚═╝",
]

def print_logo():
    W = tw()
    print()
    big_w = len(LOGO_BIG[0])
    mid_w = len(LOGO_MID[0])
    if W >= big_w + 4:
        for i, line in enumerate(LOGO_BIG):
            ratio = i / max(len(LOGO_BIG) - 1, 1)
            r = int(92  * (1 - ratio) + 180 * ratio)
            g = int(158 * (1 - ratio) + 128 * ratio)
            b = 255
            pad = (W - big_w) // 2
            print(' ' * pad + rgb(r, g, b) + BOLD + line + RESET)
    elif W >= mid_w + 4:
        for i, line in enumerate(LOGO_MID):
            ratio = i / max(len(LOGO_MID) - 1, 1)
            r = int(92  * (1 - ratio) + 180 * ratio)
            g = int(158 * (1 - ratio) + 128 * ratio)
            b = 255
            pad = (W - mid_w) // 2
            print(' ' * pad + rgb(r, g, b) + BOLD + line + RESET)
    else:
        center_print(BOLD + C_ACCENT + 'OPENMODEL' + RESET)
    print()

# ─── Panel (OpenCode-style: left blue accent bar, subtle bg) ──────────────────
def _pw():
    return min(76, max(20, tw() - 6))

def _pp():
    return max(0, (tw() - _pw()) // 2)

def _panel_row(content='', use_accent=True, accent_col=None):
    col = accent_col or C_ACCENT
    pw  = _pw()
    sp  = ' ' * _pp()
    acc = (' ' + col + '▍' + RESET) if use_accent else '  '
    vis = vis_len(content)
    pad = ' ' * max(0, pw - vis - 1)
    print(sp + BG_PANEL + acc + BG_PANEL + content + BG_PANEL + pad + RESET)

def _panel_sep():
    pw = _pw()
    sp = ' ' * _pp()
    print(sp + BG_PANEL + ' ' + C_DIM_C + '▍' + RESET +
          BG_PANEL + C_DIM_C + '─' * (pw - 1) + RESET)

def _panel_blank(dim=False):
    col = C_DIM_C if dim else C_ACCENT
    _panel_row(use_accent=True, accent_col=col)

def _model_row(model_name):
    content = (f' {DIM}{C_GRAY}agent{RESET}{BG_PANEL}   '
               f'{C_ACCENT}{BOLD}{model_name}{RESET}{BG_PANEL}   '
               f'{DIM}{C_GRAY}openmodel')
    _panel_row(content, use_accent=False)

def _hints_line():
    W  = tw()
    pw = _pw()
    pp = _pp()
    h  = (f'{DIM}{C_GRAY}tab{RESET} {C_GRAY}help'
          f'   {DIM}{C_GRAY}new{RESET} {C_GRAY}chat'
          f'   {DIM}{C_GRAY}model{RESET} {C_GRAY}switch'
          f'   {DIM}{C_GRAY}exit{RESET} {C_GRAY}quit{RESET}')
    hv  = vis_len(h)
    # right-align to match panel right edge
    pad = pp + pw + 2 - hv
    print(' ' * max(0, pad) + h)

def _panel_kv(label, value, value_color=C_WHITE):
    content = (f' {DIM}{C_GRAY}{label:<8}{RESET}{BG_PANEL} '
               f'{value_color}{value}{RESET}{BG_PANEL}')
    _panel_row(content, use_accent=True, accent_col=C_DIM_C)

# ─── Status bar ───────────────────────────────────────────────────────────────
def print_status_bar(model_name, api_ok, msg_count=0):
    dot  = (C_GREEN if api_ok else C_RED) + '●' + RESET
    msg_label = f'{msg_count} msg{"s" if msg_count != 1 else ""}' if msg_count else 'ready'
    meta = f'{os_label()}:{shell_label()}  {VERSION}'
    reserved = len(msg_label) + len(meta) + 20
    cwd = ellipsize(os.getcwd().replace(str(Path.home()), '~'), max(12, _pw() - reserved))
    mdl = ellipsize(model_name, max(12, _pw() - reserved - vis_len(cwd)))
    content = (
        f' {dot}  {DIM}{C_GRAY}{cwd}{RESET}{BG_PANEL}'
        f'  {C_ACCENT}{mdl}{RESET}{BG_PANEL}'
        f'  {DIM}{C_GRAY}{msg_label}{RESET}{BG_PANEL}'
        f'  {DIM}{C_GRAY}{meta}{RESET}{BG_PANEL}'
    )
    _panel_row(content, use_accent=True, accent_col=C_DIM_C)

# ─── Home screen ──────────────────────────────────────────────────────────────
def _home_panel(model_name, api_ok):
    cwd = ellipsize(os.getcwd().replace(str(Path.home()), '~'), max(18, _pw() - 16))
    api = 'online' if api_ok else 'offline'
    api_col = C_GREEN if api_ok else C_RED
    header = (f' {BOLD}{C_WHITE}OPENMODEL{RESET}{BG_PANEL}  '
              f'{DIM}{C_GRAY}terminal AI workspace{RESET}{BG_PANEL}')
    _panel_blank(dim=True)
    _panel_row(header, use_accent=True, accent_col=C_TEAL)
    _panel_sep()
    _panel_kv('model', ellipsize(model_name, max(12, _pw() - 16)), C_ACCENT)
    _panel_kv('shell', f'{os_label()} / {shell_label()}', C_TEAL)
    _panel_kv('api', f'● {api}', api_col)
    _panel_kv('cwd', cwd, C_GRAY)
    _panel_blank(dim=True)

def render_home(model_name, api_ok):
    clear_screen()
    print_logo()
    _home_panel(model_name, api_ok)
    print()
    _hints_line()
    print()

# ─── Windows raw input (handles wrap manually via msvcrt) ─────────────────────
def _windows_raw_input(start_col, panel_right_col, pp):
    """
    Character-by-character input for Windows.

    The full panel (including footer rows) is pre-drawn before this is called.
    When text reaches panel_right_col we:
      1. Move to next line  (\n)
      2. Insert a blank line (\033[L) — pushes footer rows down by 1
      3. Print continuation prefix (dim ▍ aligned with panel)
    On Enter we skip past the footer with \033[3B so the caller can continue
    drawing normally below it.

    line_count tracks how many extra wrapped lines we've added so that
    backspace past the start of a continuation line moves the cursor up.
    """
    import msvcrt
    pw         = panel_right_col - pp   # panel width, derived from caller args
    chars      = []
    col        = start_col
    line_count = 0          # number of wrapped continuation lines added

    # Track how many chars belong to each line so we can navigate up correctly.
    # line_lengths[0] = chars on the first (original) line,
    # line_lengths[i] = chars on continuation line i.
    # We only need to know when a line is "empty" to go back up.
    chars_per_line = [0]    # chars on each visual line (index = line_count)

    # Immediately set BG so the input row has the correct background colour
    # even before the first keypress.
    sys.stdout.write(BG_PANEL + C_WHITE)
    sys.stdout.flush()

    while True:
        ch = msvcrt.getwch()

        if ch == '\r':                          # Enter
            # \n lands cursor on the pre-drawn sep row (footer row 1).
            # \033[3B skips sep + model + blank → cursor below the panel.
            # If we've added continuation lines the footer was already pushed
            # down by line_count rows, so we only need 3B (the footer is always
            # 3 rows below the *current* line after the last wrap).
            sys.stdout.write('\n\033[3B\r')
            sys.stdout.flush()
            break

        if ch == '\x03':                        # Ctrl-C
            raise KeyboardInterrupt

        if ch == '\x08':                        # Backspace
            if chars:
                chars.pop()
                chars_per_line[line_count] -= 1

                if col > start_col:
                    # Normal backspace within current line
                    sys.stdout.write('\b \b')
                    col -= 1
                elif line_count > 0:
                    # At start of a continuation line — erase it and go up.
                    line_count -= 1
                    chars_per_line.pop()

                    # 1) Erase the continuation line visually
                    sys.stdout.write('\033[2K\r')
                    # 2) Move cursor up one row (back to previous input line)
                    sys.stdout.write('\033[1A')
                    # 3) Now delete the empty line that's sitting below the cursor
                    #    (\033[M deletes line at cursor, content below scrolls up),
                    #    restoring the footer rows to their correct position.
                    sys.stdout.write('\033[1B\033[M\033[1A')
                    # 4) Position cursor at end of previous line's text
                    prev_chars = chars_per_line[line_count]
                    col = start_col + prev_chars
                    sys.stdout.write(f'\033[{col + 1}G')  # 1-indexed absolute col
                    sys.stdout.write(BG_PANEL + C_WHITE)
                # else: at very start of first line, nothing to erase
            sys.stdout.flush()
            continue

        if ch in ('\x00', '\xe0'):              # special / arrow keys — skip
            msvcrt.getwch()
            continue

        # Ordinary printable character
        chars.append(ch)
        chars_per_line[line_count] += 1
        sys.stdout.write(ch)
        col += 1

        # Wrap at panel right edge
        if col >= panel_right_col:
            line_count += 1
            chars_per_line.append(0)
            # Panel visible width = pw cols total:
            #   ' '(1) + '▍'(1) + '  '(2) + fill(pw-4) = pw  ✓
            # typing_width = pw - 4 matches the first input line fill.
            typing_width = pw - 4
            cont = (RESET
                    + '\n\033[L'
                    + ' ' * pp                          # outside panel — no BG
                    + BG_PANEL + ' ' + C_DIM_C + '▍'   # left accent bar
                    + BG_PANEL + '  '                   # 2-space indent
                    + ' ' * typing_width                # fill panel interior with BG
                    + RESET                             # stop BG at right edge
                    + f'\033[{start_col + 1}G'          # jump cursor back to typing start
                    + BG_PANEL + C_WHITE)               # restore colour for typing
            sys.stdout.write(cont)
            col = start_col

        sys.stdout.flush()

    sys.stdout.write(RESET)
    return ''.join(chars)


# ─── Conversation input ───────────────────────────────────────────────────────
def read_input(nickname='You'):
    now = datetime.now().strftime('%H:%M')
    print()
    _msg_header(nickname, C_ACCENT, now)
    print()

    prompt_str = f'    {C_WHITE}'
    sys.stdout.flush()
    try:
        if _HAS_PT:
            user_input = _pt_prompt(
                _PT_ANSI(prompt_str),
                prompt_continuation='    ',
                multiline=False,
            )
        else:
            user_input = input(prompt_str)
    except (EOFError, KeyboardInterrupt):
        user_input = ''

    sys.stdout.write(RESET)
    print()
    return user_input.strip()

# ─── Spinner ──────────────────────────────────────────────────────────────────
def format_elapsed(seconds):
    mins = seconds // 60
    secs = seconds % 60
    hrs = mins // 60
    if hrs > 0:
        return f"{hrs}h {mins%60}m {secs}s"
    elif mins > 0:
        return f"{mins}m {secs}s"
    else:
        return f"{secs}s"

class Spinner:
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(self, label='Thinking'):
        self.label   = label
        self._stop   = threading.Event()
        self._thread = None
        self._start_time = 0
        self.streamed_text = ''

    def update_text(self, text):
        self.streamed_text = text

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
            
            max_snip_len = max(0, w - vis_len(prefix) - 5)
            if len(snippet) > max_snip_len and max_snip_len > 3:
                snippet = "..." + snippet[-(max_snip_len-3):]
            elif len(snippet) > max_snip_len:
                snippet = ""
                
            line = prefix + snippet + RESET
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

# ─── Message display ──────────────────────────────────────────────────────────
def _msg_header(label, color, ts=None):
    W   = tw()
    ts_str = f'  {DIM}{C_GRAY}{ts}{RESET}' if ts else ''
    hdr = f'  {color}{BOLD}{label}{RESET}{ts_str}'
    hv  = vis_len(hdr)
    print(hdr + '  ' + C_DIM_C + '─' * max(0, W - hv - 2) + RESET)

def print_user_msg(text, nickname='You'):
    now = datetime.now().strftime('%H:%M')
    print()
    _msg_header(nickname, C_ACCENT, now)
    print()
    W = tw()
    width = min(W - 8, 96)
    for line in text.split('\n'):
        if not line.strip():
            print()
            continue
        for row in textwrap.wrap(line, width) or ['']:
            print(f'    {C_WHITE}{row}{RESET}')
    print()

def _ai_header(model_name_str):
    print()
    _msg_header(f'AI  ·  {model_name_str}', C_ACCENT2)
    print()

# ─── Markdown renderer ────────────────────────────────────────────────────────
def render_inline(line):
    line = re.sub(r'\*\*(.+?)\*\*', lambda m: BOLD + C_WHITE + m.group(1) + RESET + C_WHITE, line)
    line = re.sub(r'\*(.+?)\*',     lambda m: ITALIC + m.group(1) + RESET + C_WHITE, line)
    line = re.sub(r'`([^`]+)`',
                  lambda m: BG_CODE + C_TEAL + ' ' + m.group(1) + ' ' + RESET + C_WHITE,
                  line)
    return line

def print_ai_response(text):
    W     = tw()
    width = min(W - 8, 96)
    lines = text.split('\n')
    in_code, lang, code_buf = False, '', []
    in_think = False

    def flush_code():
        nonlocal code_buf, lang
        if not code_buf:
            return
        cw  = width
        hdr = f'  {lang if lang else "code"} '
        print('    ' + BG_CODE + C_TEAL + BOLD + hdr + ' ' * max(0, cw - len(hdr) + 2) + RESET)
        for cl in code_buf:
            print('    ' + BG_CODE + C_TEAL + '  ' + cl + ' ' * max(0, cw - len(cl)) + RESET)
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
                lang    = line[3:].strip()
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
            pfx    = (f'    {"  " * (indent // 2)}{C_ACCENT}{marker}{RESET} '
                      if re.match(r'\d+\.', marker)
                      else f'    {"  " * (indent // 2)}{C_ACCENT}▸{RESET} ')
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

# ─── Streaming printer ────────────────────────────────────────────────────────
def confirm_cancel_request():
    try:
        ans = input(f'\n  {C_YELLOW}Точно отменить запрос? (Y/n):{RESET}  ').strip().lower()
    except KeyboardInterrupt:
        print()
        return True
    return ans not in ('n', 'no', 'н', 'нет')

def print_ai_stream(generator, mdl, control=None):
    spinner = Spinner('Thinking')
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

    def install_sigint_handler():
        nonlocal old_sigint, sigint_installed
        if threading.current_thread() is not threading.main_thread() or sigint_installed:
            return
        old_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, sigint_handler)
        sigint_installed = True

    def restore_sigint_handler():
        nonlocal sigint_installed
        if threading.current_thread() is threading.main_thread() and sigint_installed:
            signal.signal(signal.SIGINT, old_sigint)
            sigint_installed = False

    def close_active_response():
        if control is not None:
            control['cancelled'] = True
            resp = control.get('response')
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

    def stream_worker():
        try:
            for token in generator:
                if cancel_event.is_set():
                    break
                token_queue.put(('token', token))
        except BaseException as e:
            if not cancel_event.is_set():
                token_queue.put(('error', e))
        finally:
            token_queue.put((done, None))

    def handle_cancel_prompt():
        spinner.stop()
        restore_sigint_handler()
        try:
            should_cancel = confirm_cancel_request()
        finally:
            install_sigint_handler()

        if should_cancel:
            cancel_event.set()
            close_active_response()
            worker.join(timeout=1)
            print(f'\n  {DIM}{C_GRAY}[Cancelled]{RESET}\n')
            raise RequestCancelled()

        sigint_event.clear()
        print(f'  {DIM}{C_GRAY}Continuing request...{RESET}')
        spinner.start(reset_timer=False)

    worker = threading.Thread(target=stream_worker, daemon=True)
    worker.start()
    install_sigint_handler()
    spinner.start()

    try:
        while True:
            try:
                while True:
                    if sigint_event.is_set():
                        raise KeyboardInterrupt()
                    try:
                        kind, value = token_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if sigint_event.is_set():
                        raise KeyboardInterrupt()

                    if kind is done:
                        break
                    if kind == 'error':
                        raise value

                    full += value
                    spinner.update_text(full)
                break
            except KeyboardInterrupt:
                handle_cancel_prompt()
                continue
    finally:
        restore_sigint_handler()
        spinner.stop()

    elapsed = int(time.time() - start_time)

    if full.strip():
        _ai_header(mdl)
        print()
        print_ai_response(full)
        print()
        td_str = format_elapsed(elapsed)
        print(f'    {DIM}{C_GRAY}Thought for {td_str}{RESET}\n')
    return full

# ─── Config DB ────────────────────────────────────────────────────────────────
USERDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "userdata")
os.makedirs(USERDATA_DIR, exist_ok=True)

CONFIG_DB = os.path.join(USERDATA_DIR, 'config.db')
conn = sqlite3.connect(CONFIG_DB)
c    = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS config (
                id INTEGER PRIMARY KEY,
                api_key TEXT,
                model TEXT,
                nickname TEXT,
                system_prompt TEXT DEFAULT ''
            )""")
conn.commit()
c.execute('SELECT api_key, model, nickname, system_prompt FROM config WHERE id=1')
row = c.fetchone()

# ─── Setup wizard ─────────────────────────────────────────────────────────────
def setup_wizard():
    clear_screen()
    print('\n' * 3)
    center_print(C_ACCENT + BOLD + 'OPENMODEL  —  First-time setup' + RESET)
    center_print(DIM + C_GRAY + 'Takes less than a minute' + RESET)
    print()
    print(C_DIM_C + '─' * tw() + RESET)
    print()

    def ask(prompt_text, default=None):
        dflt = f'{DIM}{C_GRAY} [{default}]{RESET}' if default else ''
        sys.stdout.write(f'  {C_ACCENT}❯{RESET}  {C_WHITE}{prompt_text}{RESET}{dflt}\n'
                         f'  {C_DIM_C}└─{RESET}  ')
        sys.stdout.flush()
        val = input().strip()
        return val if val else (default or '')

    def section(label):
        print()
        print(f'  {BOLD}{C_ACCENT}{label}{RESET}')
        print(f'  {C_DIM_C}{"─" * 44}{RESET}')

    section('OPENROUTER API KEY')
    print(f'  {DIM}{C_GRAY}Get yours at: https://openrouter.ai/keys{RESET}\n')

    api_key = ask('Paste your API key')
    while not api_key:
        print(C_RED + '  ✗  API key cannot be empty.' + RESET)
        api_key = ask('Paste your API key')

    # Show the key back to the user (as requested)
    preview = api_key[:8] + '·' * min(12, max(0, len(api_key) - 12)) + api_key[-4:]
    print(f'\n  {C_GREEN}✓{RESET}  {C_WHITE}Key saved:{RESET}  {C_ACCENT}{preview}{RESET}')

    section('MODEL')
    examples = [
        ('openai/gpt-4o-mini',                'fast & cheap (default)'),
        ('anthropic/claude-3-haiku',           'smart & concise'),
        ('deepseek/deepseek-r1',               'reasoning'),
        ('meta-llama/llama-3.1-70b-instruct',  'open-source'),
    ]
    print()
    for ex, note in examples:
        print(f'  {C_DIM_C}·{RESET}  {C_ACCENT}{ex:<44}{RESET}{DIM}{C_GRAY}{note}{RESET}')
    print()
    model_name = ask('Model name', default='openai/gpt-4o-mini')

    section('NICKNAME')
    nickname = ask('Your nickname', default='user')

    section('SYSTEM PROMPT')
    print(f'  {DIM}{C_GRAY}Sent before every message. Leave blank for default.{RESET}\n')
    use_sys = ask('Use a custom system prompt? (y/n)', default='n').lower()
    system_prompt = ''
    if use_sys in ('y', 'yes', '1'):
        print(f'  {DIM}{C_GRAY}Type your prompt, press Enter twice to finish.{RESET}\n')
        buf = []
        while True:
            ln = input('  ')
            if ln == '' and buf and buf[-1] == '':
                break
            buf.append(ln)
        system_prompt = '\n'.join(buf).strip()

    print()
    print(C_DIM_C + '─' * tw() + RESET)
    print(f'\n  {C_GREEN}✓{RESET}  {C_WHITE}Setup complete! Starting OPENMODEL...{RESET}\n')
    time.sleep(1)

    c.execute(
        'INSERT INTO config (id, api_key, model, nickname, system_prompt) VALUES (1,?,?,?,?)',
        (api_key, model_name, nickname, system_prompt)
    )
    conn.commit()
    return api_key, model_name, nickname, system_prompt

# ─── Load or run setup ────────────────────────────────────────────────────────
if row:
    api_key, model_name, nickname, system_prompt = row
else:
    api_key, model_name, nickname, system_prompt = setup_wizard()

# ─── Chat DB ──────────────────────────────────────────────────────────────────
CHATS_DB = os.path.join(USERDATA_DIR, 'chats.db')
chat_conn = sqlite3.connect(CHATS_DB)
chat_c    = chat_conn.cursor()
chat_c.execute("""CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_input TEXT,
                    ai_response TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )""")
chat_conn.commit()

# ─── API check ────────────────────────────────────────────────────────────────
def check_api():
    import socket
    try:
        socket.setdefaulttimeout(3)
        socket.gethostbyname('openrouter.ai')
        return True
    except:
        return False

API_AVAILABLE = check_api()

# ─── OpenRouter streaming ─────────────────────────────────────────────────────
def shell_guidance():
    if IS_WINDOWS:
        return (
            "The command shell is Windows CMD. Use `dir` and `type` for reading files. "
            "Use `%DESKTOP%` for the Desktop path. Quote paths with spaces."
        )
    return (
        "The command shell is Linux/POSIX. Prefer `ls`, `cat`, `sed -n`, `grep`/`rg`, "
        "`python3`, and `python3 -m pip`. Use `~/Desktop`, `$DESKTOP`, or absolute "
        "paths for Desktop. Quote paths with spaces. Do not use Windows CMD syntax."
    )

def default_system_prompt():
    return (
        "You are a helpful AI assistant with full access to the user's computer. "
        "To create a new file, use EXACTLY this format:\n"
        "[NEW_FILE: path/to/file]\n...file content...\n[/NEW_FILE]\n"
        "To modify an existing file, use EXACTLY this format:\n"
        "[EDIT_FILE: path/to/file]\n...full new content...\n[/EDIT_FILE]\n"
        "Directories are created automatically, do NOT use [CMD] mkdir.\n"
        "Do NOT wrap file content in markdown code blocks. NO ```python, NO ```!\n"
        "Write the RAW file content directly inside the tags.\n"
        "Apply changes directly using [EDIT_FILE]. Do NOT create temporary files.\n"
        "To run a shell command, wrap it in [CMD]command[/CMD] tags. "
        "You will receive the command output in the next message. "
        "Read-only inspection commands may execute silently in the background.\n"
        f"{shell_guidance()} "
        "Format other responses with markdown. Always confirm before destructive actions."
    )

DEFAULT_SYS = default_system_prompt()

def runtime_system_context():
    return (
        f"CURRENT DIRECTORY: {os.getcwd()}\n"
        f"OPERATING SYSTEM: {os_label()}\n"
        f"SHELL: {shell_label()}\n"
        f"DESKTOP DIRECTORY: {get_desktop()}\n"
        f"COMMAND GUIDANCE: {shell_guidance()}"
    )

def stream_openrouter(messages, extra_system=None, control=None):
    if not API_AVAILABLE:
        yield '[API UNAVAILABLE] Cannot reach openrouter.ai'
        return
    headers = {'Authorization': f'Bearer {api_key}',
               'Content-Type': 'application/json',
               'HTTP-Referer': 'https://openrouter.ai'}
    sys_msg = extra_system or system_prompt or DEFAULT_SYS
    sys_msg += f"\n\n{runtime_system_context()}"
    payload = {'model': model_name,
               'messages': [{'role': 'system', 'content': sys_msg}] + messages,
               'stream': True,
               'include_reasoning': True}
    try:
        in_reasoning = False
        with requests.post('https://openrouter.ai/api/v1/chat/completions',
                           headers=headers, json=payload, stream=True, timeout=60) as resp:
            if control is not None:
                control['response'] = resp
            resp.encoding = 'utf-8'
            if resp.status_code != 200:
                yield f'[API ERROR] HTTP {resp.status_code}: {resp.text[:300]}'
                return
            for line in resp.iter_lines(decode_unicode=True):
                if control is not None and control.get('cancelled'):
                    return
                if not line or line.startswith(':'):
                    continue
                if line.startswith('data: '):
                    line = line[6:]
                if not line or line == '[DONE]':
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if 'choices' in data and data['choices']:
                    delta = data['choices'][0].get('delta', {})
                    reasoning_chunk = delta.get('reasoning', '')
                    content_chunk = delta.get('content', '')
                    
                    if reasoning_chunk:
                        if not in_reasoning:
                            yield '<think>\n'
                            in_reasoning = True
                        yield reasoning_chunk
                        
                    if content_chunk:
                        if in_reasoning:
                            yield '\n</think>\n'
                            in_reasoning = False
                        yield content_chunk
        if in_reasoning:
            yield '\n</think>\n'
    except Exception as e:
        if control is not None and control.get('cancelled'):
            return
        yield f'[API ERROR] {e}'
    finally:
        if control is not None:
            control.pop('response', None)

# ─── System command helpers ───────────────────────────────────────────────────
def get_desktop():
    if IS_WINDOWS:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
            d, _ = winreg.QueryValueEx(k, 'Desktop')
            winreg.CloseKey(k)
            if os.path.exists(d):
                return d
        except:
            pass
        for p in [Path.home() / 'Desktop', Path.home() / 'OneDrive' / 'Desktop']:
            if p.exists():
                return str(p)
        return os.path.expandvars(r'%USERPROFILE%\Desktop')
    xdg_cfg = Path.home() / '.config' / 'user-dirs.dirs'
    try:
        if xdg_cfg.exists():
            for line in xdg_cfg.read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('XDG_DESKTOP_DIR='):
                    value = line.split('=', 1)[1].strip().strip('"')
                    value = value.replace('$HOME', str(Path.home()))
                    desktop = os.path.expandvars(os.path.expanduser(value))
                    if desktop:
                        return desktop
    except Exception:
        pass
    return str(Path.home() / 'Desktop')

def expand_desktop_token(text):
    desktop = get_desktop()
    text = str(text).replace('%DESKTOP%', desktop)
    return re.sub(r'\$\{DESKTOP\}|\$DESKTOP\b', lambda _m: desktop, text)

def expand_special_path(path):
    path = expand_desktop_token(path).strip().strip('"\'')
    return os.path.expandvars(os.path.expanduser(path))

def command_env():
    env = os.environ.copy()
    env['DESKTOP'] = get_desktop()
    env.setdefault('PYTHONUTF8', '1')
    return env

def execute_command(cmd):
    cmd = expand_desktop_token(cmd)
    if cmd.lower().strip().startswith('cd '):
        target = expand_special_path(cmd.strip()[3:].strip())
        try:
            os.chdir(target)
            return f"[Directory changed to {os.getcwd()}]"
        except Exception as e:
            return f"[ERROR] {e}"
    try:
        if IS_WINDOWS:
            # chcp 65001 ensures Cyrillic paths and output work correctly
            full_cmd = f'chcp 65001 >nul 2>&1 & {cmd}'
            r = subprocess.run(
                ['cmd.exe', '/c', full_cmd],
                capture_output=True, text=True,
                timeout=30, encoding='utf-8', errors='replace',
                env=command_env()
            )
        else:
            shell_exe = os.environ.get('SHELL')
            if shell_exe and not os.path.exists(shell_exe):
                shell_exe = None
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=30, encoding='utf-8', errors='replace',
                               env=command_env(), executable=shell_exe)
        out = r.stdout.strip()
        err = r.stderr.strip()
        return (out + ('\n' + err if err else '')) or '[Command executed successfully]'
    except subprocess.TimeoutExpired:
        return '[ERROR] Command timed out'
    except Exception as e:
        return f'[ERROR] {e}'

def confirm_exec(cmd):
    print()
    print(f'  {C_YELLOW}⚡  OPENMODEL wants to run:{RESET}')
    print()
    cw = min(tw() - 8, 80)
    print('    ' + BG_CODE + C_TEAL + f'  {cmd:<{cw}}' + RESET)
    print()
    ans = input(f'  {C_YELLOW}Execute? (y/n):{RESET}  ').strip().lower()
    return ans in ('y', 'yes', '1')

# ─── File helpers ─────────────────────────────────────────────────────────────
READ_ONLY_COMMANDS = {
    'cat', 'cd', 'dir', 'file', 'find', 'grep', 'head', 'ls', 'pwd', 'realpath',
    'rg', 'sed', 'stat', 'tail', 'tree', 'type', 'wc', 'where', 'which',
}

READ_ONLY_PREFIXES = (
    'git status', 'git diff', 'git log', 'git show', 'git branch --show-current',
    'python -m py_compile ', 'python3 -m py_compile ',
)

def command_verb(cmd):
    try:
        parts = shlex.split(cmd, posix=not IS_WINDOWS)
        return parts[0].lower() if parts else ''
    except Exception:
        return cmd.strip().split(maxsplit=1)[0].lower() if cmd.strip() else ''

def is_read_only_command(cmd):
    low = cmd.strip().lower()
    if not low:
        return True
    if any(low.startswith(prefix) for prefix in READ_ONLY_PREFIXES):
        return True
    if re.search(r'(^|[;&|]\s*)(sudo|rm|mv|cp|chmod|chown|truncate|tee|dd|mkfs|mount|umount|apt|apt-get|dnf|pacman|zypper|pip|pip3|npm|pnpm|yarn|git)\b', low):
        return False
    if '>' in low or re.search(r'\b-delete\b|\b-exec\b', low):
        return False
    if re.search(r'\bsed\b.*\s-i(\s|$)', low):
        return False
    return command_verb(low) in READ_ONLY_COMMANDS

def resolve_path(path, base_dir=None):
    path = clean_path(expand_special_path(path))
    if os.path.isabs(path):
        return path
    return os.path.join(base_dir or os.getcwd(), path)

def detect_read(text):
    for p in [
        r"(?:прочитай|расскажи|объясни|проанализируй)\s+файл\s+['\"](.+?)['\"](?:\s+(?:и\s+)?(.+?))?$",
        r"read\s+file\s+['\"](.+?)['\"](?:\s+and\s+(.+?))?$",
        r"(?:прочитай|расскажи|объясни|проанализируй)\s+файл\s+([^\s]+)(?:\s+(?:и\s+)?(.+?))?$",
        r"(?:read|analyze|explain)\s+(?:file\s+)?([^\s]+\.[\w]+)(?:\s+and\s+(.+?))?$",
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip('"\''), (m.group(2).strip() if m.group(2) else None)
    return None, None

def detect_modify(text):
    m = re.search(r'(?:измени|modify|change|edit)\s+([^\s]+)\s+(.*)', text, re.IGNORECASE)
    return (m.group(1).strip('"\''), m.group(2).strip()) if m else (None, None)

def detect_create_project(text):
    """Detect create/build <X> by/from prompt/spec/readme <path>"""
    patterns = [
        r'(?:создай|сделай|напиши|разработай|сгенерируй|create|build|make|init|start|generate|develop|code|write|craete|creet)\s+.{0,50}?\s+(?:по|из|следуя|согласно|используя|на основе|by|from|using|following|with|based on)\s+(?:this\s+|этому?\s+)?(?:prompt|readme|spec|file|description|промту?|промпту?|файлу?|описанию?)?[:\s]*["\'](.+?)["\']',
        r'(?:создай|сделай|напиши|разработай|сгенерируй|create|build|make|init|start|generate|develop|code|write|craete|creet)\s+.{0,50}?\s+(?:по|из|следуя|согласно|используя|на основе|by|from|using|following|with|based on)\s+(?:this\s+|этому?\s+)?(?:prompt|readme|spec|file|description|промту?|промпту?|файлу?|описанию?)?[:\s]*([^\s"\']+(\.[a-zA-Z]+))',
    ]
    for p in patterns:
        m = re.search(p, text.strip(), re.IGNORECASE)
        if m:
            return m.group(1).strip().strip('"\'')
    return None

def show_help():
    W = tw()
    print()
    label = f'  {C_ACCENT}{BOLD}COMMANDS{RESET}'
    print(label + '  ' + C_DIM_C + '─' * max(0, W - vis_len(label) - 2) + RESET)
    print()
    cmds = [
        ('exit / quit',           'Exit OPENMODEL'),
        ('cls / clear',           'Back to home screen'),
        ('new',                   'Fresh conversation (reset context)'),
        ('model <name>',          'Switch AI model (saved to config)'),
        ('history',               'Show last 10 conversations'),
        ('config',                'Show current configuration'),
        ('reset config',          'Delete config & re-run setup'),
        ('read file <path>',      'Read & analyse a file with AI'),
        ('modify <path> <task>',  'Ask AI to edit a file'),
        ('tab / help / ?',        'Show this help'),
    ]
    ml = max(len(k) for k, _ in cmds)
    for k, v in cmds:
        print(f'  {C_ACCENT}{k:<{ml + 2}}{RESET}  {DIM}{C_GRAY}{v}{RESET}')
    print()

def show_history():
    chat_c.execute('SELECT user_input, ai_response, timestamp FROM chats ORDER BY id DESC LIMIT 10')
    rows = chat_c.fetchall()
    if not rows:
        print(f'\n  {C_GRAY}No history yet.{RESET}\n')
        return
    W = tw()
    print()
    label = f'  {C_ACCENT}{BOLD}HISTORY{RESET}  {DIM}{C_GRAY}last 10{RESET}'
    print(label + '  ' + C_DIM_C + '─' * max(0, W - vis_len(label) - 2) + RESET)
    for u, a, ts in reversed(rows):
        print()
        print(f'  {DIM}{C_GRAY}{ts}{RESET}')
        print(f'  {C_ACCENT}You:{RESET}  {C_WHITE}{u[:120]}{RESET}')
        print(f'  {C_ACCENT2}AI: {RESET}  {C_GRAY}{(a or "")[:180].replace(chr(10), " ")}{RESET}')
    print()

def show_config():
    W = tw()
    print()
    label = f'  {C_ACCENT}{BOLD}CONFIG{RESET}'
    print(label + '  ' + C_DIM_C + '─' * max(0, W - vis_len(label) - 2) + RESET)
    print()
    # Show full key so the user can see what they entered
    key_disp = api_key
    sp_prev  = (system_prompt[:72] + '…') if len(system_prompt) > 72 \
               else (system_prompt or f'{DIM}{C_GRAY}(default){RESET}')
    rows = [
        ('API key',       key_disp),
        ('Model',         model_name),
        ('Nickname',      nickname),
        ('System prompt', sp_prev),
        ('API status',    (C_GREEN + '● online' if API_AVAILABLE else C_RED + '● offline') + RESET),
    ]
    ml = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f'  {C_GRAY}{k:<{ml + 2}}{RESET}  {C_WHITE}{v}{RESET}')
    print()

# ─── Main loop ────────────────────────────────────────────────────────────────
def main():
    global model_name, API_AVAILABLE

    conversation: list[dict] = []
    msg_count = 0

    render_home(model_name, API_AVAILABLE)

    while True:
        try:
            user_input = read_input(nickname)
        except (EOFError, KeyboardInterrupt):
            print(f'\n\n  {DIM}{C_GRAY}Goodbye.{RESET}\n')
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ('exit', 'quit', 'q'):
            print(f'\n  {DIM}{C_GRAY}Goodbye.{RESET}\n')
            break

        if lower in ('cls', 'clear'):
            render_home(model_name, API_AVAILABLE)
            continue

        if lower == 'new':
            conversation.clear()
            msg_count = 0
            render_home(model_name, API_AVAILABLE)
            print()
            center_print(C_GREEN + '✓  New conversation started' + RESET)
            print()
            continue

        if lower in ('tab', 'help', '?'):
            show_help()
            continue

        if lower == 'history':
            show_history()
            continue

        if lower == 'config':
            show_config()
            continue

        if lower == 'reset config':
            c.execute('DELETE FROM config WHERE id=1')
            conn.commit()
            print(f'\n  {C_YELLOW}Config deleted. Restart to re-run setup.{RESET}\n')
            time.sleep(1.5)
            break

        if lower.startswith('model '):
            nm = user_input[6:].strip()
            if nm:
                model_name = nm
                c.execute('UPDATE config SET model=? WHERE id=1', (model_name,))
                conn.commit()
                print(f'\n  {C_GREEN}✓{RESET}  Model → {C_ACCENT}{model_name}{RESET}\n')
            else:
                print(f'\n  {C_RED}Usage: model <model-name>{RESET}\n')
            continue

        if lower.startswith('cd '):
            new_dir = expand_special_path(user_input[3:].strip())
            try:
                os.chdir(new_dir)
                print(f'\n  {C_GREEN}✓{RESET}  Changed directory to: {C_ACCENT}{os.getcwd()}{RESET}\n')
            except Exception as e:
                print(f'\n  {C_RED}✗  Cannot change directory: {e}{RESET}\n')
            continue

        # ── Create project by prompt ───────────────────────────────────────────
        proj_path = detect_create_project(user_input)
        if proj_path:
            # Resolve path (handles spaces, Cyrillic, relative paths)
            proj_path = resolve_path(proj_path.strip())
            if not os.path.exists(proj_path):
                print(f'\n  {C_RED}✗  File not found: {proj_path}{RESET}\n')
                continue

            # ── Read file SILENTLY via Python (no CMD, no confirmation) ────────
            try:
                prompt_content = open(proj_path, encoding='utf-8', errors='replace').read()
            except Exception as e:
                print(f'\n  {C_RED}✗  Cannot read file: {e}{RESET}\n')
                continue

            # Project dir = folder containing the prompt file
            project_dir = os.path.dirname(os.path.abspath(proj_path))

            project_sys = (
                "You are an expert software developer. "
                "The user has provided a project specification/README. "
                "Your job is to fully implement the project described. "
                "To create a file, you MUST use exactly this format:\n"
                "[NEW_FILE: path/relative/to/project]\n...content...\n[/NEW_FILE]\n"
                "Directories are created automatically, do NOT use [CMD] mkdir.\n"
                "Do NOT wrap the file content in markdown code blocks. Use RAW text only!\n"
                "For every shell command to run (install deps, init git, etc.), use [CMD]command[/CMD]. "
                "In [CMD] blocks, use paths relative to the project directory or absolute paths. "
                f"Commands run on {os_label()} using {shell_label()}. {shell_guidance()} "
                "Do NOT ask clarifying questions — implement everything described. "
                "Use markdown in explanations only, not inside file content tags."
            )
            build_prompt = (
                f"PROJECT DIRECTORY: {project_dir}\n\n"
                f"SPECIFICATION:\n```\n{prompt_content}\n```\n\n"
                "Implement this project fully. Create all necessary files and run all needed commands."
            )

            try:
                control = {}
                full = print_ai_stream(
                    stream_openrouter(
                        [{'role': 'user', 'content': build_prompt}],
                        extra_system=project_sys,
                        control=control
                    ),
                    model_name,
                    control
                )

                # ── Auto-create files (no confirmation needed) ─────────────
                for rel_path, content in re.findall(
                        r'\[NEW_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/NEW_FILE\]|(?=\[(?:NEW_FILE|CMD))|\Z)', full, re.DOTALL):
                    rel_path = clean_path(expand_special_path(rel_path))
                    if is_dummy_path(rel_path): continue
                    abs_path = resolve_path(rel_path, project_dir)
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    open(abs_path, 'w', encoding='utf-8').write(clean_content(content) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Created: {C_ACCENT}{abs_path}{RESET}\n')

                # ── Auto-execute setup commands (no confirmation) ──────────
                for cmd in re.findall(r'\[CMD\](.*?)\[/CMD\]', full, re.DOTALL):
                    cmd = cmd.strip()
                    if not cmd:
                        continue
                    # Run commands from project directory
                    orig_cwd = os.getcwd()
                    try:
                        os.chdir(project_dir)
                        out = execute_command(cmd)
                    finally:
                        os.chdir(orig_cwd)
                    if out and out != '[Command executed successfully]':
                        print(f'\n    {C_GRAY}{out[:400]}{RESET}\n')

                chat_c.execute('INSERT INTO chats (user_input, ai_response) VALUES (?,?)',
                               (user_input, full))
                chat_conn.commit()
            except RequestCancelled:
                pass
            except Exception as e:
                print(f'\n  {C_RED}Error: {e}{RESET}\n')
            continue

        # ── File read ──────────────────────────────────────────────────────────
        fp, inst = detect_read(user_input)
        if fp:
            fp = resolve_path(fp)
            if not os.path.exists(fp):
                print(f'\n  {C_RED}✗  File not found: {fp}{RESET}\n')
                continue
            try:
                content = open(fp, encoding='utf-8', errors='replace').read()
                task    = inst or 'Summarize this file and explain what it does.'
                sys_m   = ('You are a code analysis assistant. '
                           'Use clear markdown formatting. No [CMD] tags.')
                prompt  = f'FILE PATH: {fp}\n\nCONTENT:\n```\n{content}\n```\n\nTASK: {task}'
                control = {}
                full    = print_ai_stream(
                    stream_openrouter([{'role': 'user', 'content': prompt}],
                                      extra_system=sys_m, control=control),
                    model_name, control)
                chat_c.execute('INSERT INTO chats (user_input, ai_response) VALUES (?,?)',
                               (user_input, full))
                chat_conn.commit()
            except RequestCancelled:
                pass
            except Exception as e:
                print(f'\n  {C_RED}Error: {e}{RESET}\n')
            continue

        # ── File modify ────────────────────────────────────────────────────────
        mfp, mtask = detect_modify(user_input)
        if mfp and mtask:
            mfp = resolve_path(mfp)
            if not os.path.exists(mfp):
                print(f'\n  {C_RED}✗  File not found: {mfp}{RESET}\n')
                continue
            try:
                orig   = open(mfp, encoding='utf-8', errors='replace').read()
                prompt = (f'FILE: {mfp}\n\nORIGINAL:\n```\n{orig}\n```\n\n'
                          f'REQUEST: {mtask}\n\n'
                          'Modified file → [EDIT_FILE: path]...[/EDIT_FILE]\n'
                          'New file → [NEW_FILE: path]...[/NEW_FILE] (Directories are created automatically)\n'
                          'Do NOT wrap code inside tags with ``` blocks. Use RAW text.\n'
                          'Shell cmd → [CMD]cmd[/CMD]')
                control = {}
                full = print_ai_stream(
                    stream_openrouter([{'role': 'user', 'content': prompt}], control=control),
                    model_name, control)
                
                m_old = re.search(r'\[MODIFIED_FILE\](.*?)\[/MODIFIED_FILE\]', full, re.DOTALL)
                if m_old:
                    open(mfp, 'w', encoding='utf-8').write(clean_content(m_old.group(1)) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Updated: {C_ACCENT}{mfp}{RESET}\n')
                
                for efp, ec in re.findall(r'\[EDIT_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/EDIT_FILE\]|(?=\[(?:NEW_FILE|EDIT_FILE|CMD))|\Z)', full, re.DOTALL):
                    efp = clean_path(expand_special_path(efp))
                    if is_dummy_path(efp): continue
                    efp = resolve_path(efp, os.path.dirname(os.path.abspath(mfp)))
                    os.makedirs(os.path.dirname(efp), exist_ok=True)
                    open(efp, 'w', encoding='utf-8').write(clean_content(ec) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Updated: {C_ACCENT}{efp}{RESET}\n')

                for nfp, nc in re.findall(r'\[NEW_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/NEW_FILE\]|(?=\[(?:NEW_FILE|EDIT_FILE|CMD))|\Z)', full, re.DOTALL):
                    nfp = clean_path(expand_special_path(nfp))
                    if is_dummy_path(nfp): continue
                    nfp = resolve_path(nfp, os.path.dirname(os.path.abspath(mfp)))
                    os.makedirs(os.path.dirname(nfp), exist_ok=True)
                    open(nfp, 'w', encoding='utf-8').write(clean_content(nc) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Created: {C_ACCENT}{nfp}{RESET}\n')
                for cmd in re.findall(r'\[CMD\](.*?)\[/CMD\]', full, re.DOTALL):
                    cmd = cmd.strip()
                    if cmd and confirm_exec(cmd):
                        out = execute_command(cmd)
                        print(f'\n    {C_GRAY}{out}{RESET}\n')
                chat_c.execute('INSERT INTO chats (user_input, ai_response) VALUES (?,?)',
                               (user_input, full))
                chat_conn.commit()
            except RequestCancelled:
                pass
            except Exception as e:
                print(f'\n  {C_RED}Error: {e}{RESET}\n')
            continue

        # ── Normal multi-turn chat ─────────────────────────────────────────────
        conversation.append({'role': 'user', 'content': user_input})
        msg_count += 1

        agent_loop_count = 0
        while agent_loop_count < 5:
            agent_loop_count += 1
            full = ''
            try:
                control = {}
                full = print_ai_stream(
                    stream_openrouter(conversation, control=control),
                    model_name,
                    control
                )
            except RequestCancelled:
                conversation.pop()
                msg_count -= 1
                break
            except KeyboardInterrupt:
                print(f'\n  {C_GRAY}[Cancelled]{RESET}\n')
                conversation.pop()
                msg_count -= 1
                break

            if full:
                conversation.append({'role': 'assistant', 'content': full})

            for nfp, nc in re.findall(r'\[NEW_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/NEW_FILE\]|(?=\[(?:NEW_FILE|EDIT_FILE|CMD))|\Z)', full, re.DOTALL):
                nfp = clean_path(expand_special_path(nfp))
                if is_dummy_path(nfp): continue
                nfp = resolve_path(nfp)
                try:
                    os.makedirs(os.path.dirname(nfp), exist_ok=True)
                    open(nfp, 'w', encoding='utf-8').write(clean_content(nc) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Created: {C_ACCENT}{nfp}{RESET}\n')
                except Exception as e:
                    print(f'  {C_RED}✗  Could not create {nfp}: {e}{RESET}\n')

            for efp, ec in re.findall(r'\[EDIT_FILE[\s:\]]*([^\]\n<>]+)[\]\s]*(.*?)(?:\[/EDIT_FILE\]|(?=\[(?:NEW_FILE|EDIT_FILE|CMD))|\Z)', full, re.DOTALL):
                efp = clean_path(expand_special_path(efp))
                if is_dummy_path(efp): continue
                efp = resolve_path(efp)
                try:
                    os.makedirs(os.path.dirname(efp), exist_ok=True)
                    open(efp, 'w', encoding='utf-8').write(clean_content(ec) + '\n')
                    print(f'  {C_GREEN}✓{RESET}  Updated: {C_ACCENT}{efp}{RESET}\n')
                except Exception as e:
                    print(f'  {C_RED}✗  Could not update {efp}: {e}{RESET}\n')

            cmds = re.findall(r'\[CMD\](.*?)\[/CMD\]', full, re.DOTALL)
            if not cmds:
                chat_c.execute('INSERT INTO chats (user_input, ai_response) VALUES (?,?)',
                               (user_input, full))
                chat_conn.commit()
                break

            cmd_results = []
            for cmd in cmds:
                cmd = cmd.strip()
                if not cmd: continue
                # Silent execution for safe reading commands
                if is_read_only_command(cmd):
                    out = execute_command(cmd)
                    cmd_results.append(f"Result of `{cmd}`:\n```\n{out}\n```")
                else:
                    if confirm_exec(cmd):
                        out = execute_command(cmd)
                        print(f'\n    {C_GRAY}{out}{RESET}\n')
                        cmd_results.append(f"Result of `{cmd}`:\n```\n{out}\n```")
                    else:
                        cmd_results.append(f"Result of `{cmd}`: [USER DENIED EXECUTION]")
            
            if cmd_results:
                msg = "Command outputs:\n" + "\n\n".join(cmd_results)
                conversation.append({'role': 'user', 'content': msg})
                msg_count += 1
                continue

    conn.close()
    chat_conn.close()

if __name__ == '__main__':
    main()
