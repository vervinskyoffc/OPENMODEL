# OPENMODEL

OPENMODEL is a terminal AI workspace for OpenRouter models. It can chat, inspect files, create or edit project files through tagged responses, and run shell commands with confirmation for non-read-only actions.

## Linux quick start

Requirements:

- Python 3.10+
- `python3-venv`
- Internet access for installing Python packages and calling OpenRouter

Run:

```bash
chmod +x start.sh
./start.sh
```

On the first launch, paste your OpenRouter API key and choose a model. User settings and chat history are stored in `userdata/`.

## Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## Notes

- Linux commands are now the default runtime guidance for the AI agent.
- `$DESKTOP`, `${DESKTOP}`, and `%DESKTOP%` are expanded to the detected Desktop directory.
- Read-only commands such as `ls`, `cat`, `sed -n`, `rg`, `grep`, `find`, `pwd`, `git diff`, and `git status` can run silently; commands that may change files or the system still ask for confirmation.
