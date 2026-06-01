#!/usr/bin/env python3
"""cc-branch-tree engine.

Parses Claude Code transcripts, rebuilds the conversation fork tree, and resolves
a node selector to (session_id, cwd) for resuming.

Verified Claude Code behavior this relies on (see docs/specs):
  * Transcripts live at  <projects_dir>/<encoded-cwd>/<session-id>.jsonl  (JSONL).
  * `/branch` copies the parent's history into a NEW session file and stamps every
    inherited entry with top-level `forkedFrom = {sessionId, messageUuid}`, where
    `forkedFrom.sessionId` is the IMMEDIATE parent (constant within a file).  [F5]
  * Equivalent cross-check: the author (owner) of a session's LAST inherited message
    is that same immediate parent.  [F6]  We do NOT use naive uuid-set containment,
    which false-positives on siblings forked at the same depth.

Zero third-party dependencies (Python 3.8+ stdlib only).
"""
from __future__ import annotations

import calendar
import glob
import json
import os
import re
import sys
import time

MSG_TYPES = ("user", "assistant")

# Strip Claude Code's wrapper blocks when falling back to a first-message preview.
_WRAPPER_RE = re.compile(
    r"<(local-command-caveat|local-command-stdout|command-message|command-name|"
    r"command-args|system-reminder)\b[^>]*>.*?</\1>",
    re.S,
)


# --------------------------------------------------------------------------- paths
def projects_dir():
    return os.environ.get("CC_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")


def data_dir():
    d = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.cache/cc-branch-tree")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- model
class Session:
    __slots__ = (
        "sid", "cwd", "git_branch", "forked_from_sid", "inherited_in_order",
        "all_uuids", "inherited_uuids", "msg_uuids", "label", "created", "last", "msgs",
    )

    def __init__(self, sid):
        self.sid = sid
        self.cwd = None
        self.git_branch = None
        self.forked_from_sid = None
        self.inherited_in_order = []
        self.all_uuids = set()
        self.inherited_uuids = set()
        self.msg_uuids = []
        self.label = "(untitled)"
        self.created = None
        self.last = None
        self.msgs = 0


def _title_text(obj):
    for k, v in obj.items():
        if k not in ("type", "sessionId", "uuid", "parentUuid", "timestamp") \
                and isinstance(v, str) and 0 < len(v) < 120:
            return v
    return None


def _msg_preview(message, n=46):
    if not isinstance(message, dict):
        return None
    c = message.get("content")
    raw = None
    if isinstance(c, str):
        raw = c
    elif isinstance(c, list):
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                raw = block.get("text")
                break
    if not raw:
        return None
    raw = _WRAPPER_RE.sub(" ", raw)
    for line in raw.splitlines():
        line = line.strip()
        if line:
            return line[:n]
    return None


# --------------------------------------------------------------------------- parse
def parse_transcript(path):
    s = Session(os.path.basename(path)[:-6])
    custom_title = ai_title = first_user = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            u = o.get("uuid")
            if u:
                s.all_uuids.add(u)
            ff = o.get("forkedFrom")
            if isinstance(ff, dict):
                if s.forked_from_sid is None:
                    s.forked_from_sid = ff.get("sessionId")
                if u:
                    s.inherited_uuids.add(u)
                    s.inherited_in_order.append(u)
            if s.cwd is None and o.get("cwd"):
                s.cwd = o["cwd"]
                s.git_branch = o.get("gitBranch")
            if t == "custom-title":
                custom_title = _title_text(o) or custom_title
            elif t == "ai-title":
                ai_title = _title_text(o) or ai_title
            if t in MSG_TYPES and not o.get("isSidechain"):
                s.msgs += 1
                if u:
                    s.msg_uuids.append(u)
                ts = o.get("timestamp")
                if ts:
                    if s.created is None:
                        s.created = ts
                    s.last = ts
                if t == "user" and first_user is None:
                    first_user = _msg_preview(o.get("message"))
    s.label = custom_title or ai_title or first_user or "(untitled)"
    return s


def load_sessions():
    sessions = {}
    for path in glob.glob(os.path.join(projects_dir(), "*", "*.jsonl")):
        try:
            s = parse_transcript(path)
        except OSError:
            continue
        sessions[s.sid] = s
    return sessions


# --------------------------------------------------------------------------- tree
def build_owner_index(sessions):
    """owner[uuid] = session that originally authored it (present and not inherited)."""
    owner = {}
    for s in sessions.values():
        for u in (s.all_uuids - s.inherited_uuids):
            owner[u] = s.sid
    return owner


def immediate_parent(s, sessions, owner=None):
    """Immediate parent session id, or None for a root / orphan.

    Primary (F5): forkedFrom.sessionId.  Fallback (F6, for legacy transcripts with no
    forkedFrom): author of the last inherited message.  Never uses set containment.
    """
    p = s.forked_from_sid
    if p is None and owner is not None and s.inherited_in_order:
        p = owner.get(s.inherited_in_order[-1])
    return p if p in sessions else None


def build_forest(sessions, owner=None):
    children = {}
    roots = []
    for sid, s in sessions.items():
        p = immediate_parent(s, sessions, owner)
        if p:
            children.setdefault(p, []).append(sid)
        else:
            roots.append(sid)
    return children, roots


def fork_depth(child, sessions):
    """How many of the parent's own messages this child inherited (its fork point)."""
    p = child.forked_from_sid
    if p in sessions:
        return len(child.inherited_uuids & set(sessions[p].msg_uuids))
    return None


# --------------------------------------------------------------------------- render
def _idle(ts):
    if not ts:
        return "?"
    try:
        secs = time.time() - calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return "?"
    if secs < 3600:
        return "%dm" % int(secs // 60)
    if secs < 86400:
        return "%dh" % int(secs // 3600)
    return "%dd" % int(secs // 86400)


def _sort_key(sessions):
    return lambda sid: (sessions[sid].created or "", sid)


def render(sessions, children, roots, filter_str=None):
    by_proj = {}
    for sid in roots:
        proj = sessions[sid].cwd or "(unknown)"
        by_proj.setdefault(proj, []).append(sid)
    lines = []
    ordered = []
    for proj in sorted(by_proj):
        if filter_str and filter_str.lower() not in proj.lower():
            continue
        lines.append("\U0001F4C1 %s" % proj)
        for sid in sorted(by_proj[proj], key=_sort_key(sessions)):
            _emit(sid, 0, sessions, children, lines, ordered)
        lines.append("")
    text = "\n".join(lines).rstrip()
    return text, ordered


def _emit(sid, depth, sessions, children, lines, ordered):
    s = sessions[sid]
    idx = len(ordered)
    ordered.append(sid)
    prefix = "  " + "│  " * (depth - 1) + "└─ " if depth else "  "
    extra = (" · %s" % s.git_branch) if s.git_branch else ""
    d = fork_depth(s, sessions)
    if d is not None:
        extra += "  ↳forked after %d msg" % d
    lines.append("%s[%d] %s · %s · %dmsg · %s%s"
                 % (prefix, idx, s.sid[:8], s.label[:32], s.msgs, _idle(s.last), extra))
    for c in sorted(children.get(sid, []), key=_sort_key(sessions)):
        _emit(c, depth + 1, sessions, children, lines, ordered)


# --------------------------------------------------------------------------- resolve
def _last_tree_path():
    return os.path.join(data_dir(), "last_tree.json")


def write_last_tree(ordered, sessions):
    payload = [
        {"idx": i, "sid": sessions[sid].sid, "cwd": sessions[sid].cwd, "label": sessions[sid].label}
        for i, sid in enumerate(ordered)
    ]
    with open(_last_tree_path(), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def load_last_tree():
    try:
        with open(_last_tree_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []


def resolve(selector, sessions=None):
    """Resolve an index / sid-prefix / label-substring to (sid, cwd), or None."""
    selector = (selector or "").strip()
    if not selector:
        return None
    if selector.isdigit():
        nodes = load_last_tree()
        i = int(selector)
        if 0 <= i < len(nodes):
            return nodes[i]["sid"], nodes[i]["cwd"]
    if sessions is None:
        sessions = load_sessions()
    for sid, s in sessions.items():
        if sid.startswith(selector):
            return sid, s.cwd
    low = selector.lower()
    for sid, s in sessions.items():
        if s.label and low in s.label.lower():
            return sid, s.cwd
    return None


# --------------------------------------------------------------------------- CLI
def _needs_owner(sessions):
    return any(s.forked_from_sid is None and s.inherited_in_order for s in sessions.values())


def cmd_render(filter_str=None):
    sessions = load_sessions()
    owner = build_owner_index(sessions) if _needs_owner(sessions) else None
    children, roots = build_forest(sessions, owner)
    text, ordered = render(sessions, children, roots, filter_str)
    write_last_tree(ordered, sessions)
    print(text if text else "No sessions found.")
    return 0


def cmd_resume(args):
    launch = "--launch" in args
    selector = next((a for a in args if a != "--launch"), "")
    hit = resolve(selector)
    if not hit:
        print("No matching node for: %r" % selector)
        return 1
    sid, cwd = hit
    cwd = cwd or os.getcwd()
    if launch:
        launcher = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launch.sh")
        os.execv("/bin/bash", ["/bin/bash", launcher, cwd, sid])
    print('cd "%s" && claude --resume %s' % (cwd, sid))
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "render"
    if cmd == "render":
        return cmd_render(" ".join(argv[2:]).strip() or None)
    if cmd == "resume":
        return cmd_resume(argv[2:])
    print("unknown command: %s (use 'render' or 'resume')" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
