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
    # A session whose first message is a slash-command invocation: label it by the
    # command name (e.g. "/deploy"), not the rendered command body.
    cmd = re.search(r"<command-name>\s*(\S[^<]*?)\s*</command-name>", raw)
    if cmd:
        return cmd.group(1).strip()[:n]
    raw = _WRAPPER_RE.sub(" ", raw)
    for line in raw.splitlines():
        line = line.strip()
        if line:
            return line[:n]
    return None


# --------------------------------------------------------------------------- parse
def _encode_cwd(path):
    """Replicate Claude Code's cwd -> project-folder encoding."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def parse_transcript(path):
    s = Session(os.path.basename(path)[:-6])
    folder = os.path.basename(os.path.dirname(path))
    custom_title = ai_title = first_user = None
    first_cwd = first_git = matched_cwd = matched_git = None
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
            if o.get("cwd"):
                cw = o["cwd"]
                if first_cwd is None:
                    first_cwd, first_git = cw, o.get("gitBranch")
                if matched_cwd is None and _encode_cwd(cw) == folder:
                    matched_cwd, matched_git = cw, o.get("gitBranch")
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
    # Prefer the cwd whose encoding matches the session's project folder (the true
    # resume target); fall back to the first cwd seen (e.g. mid-session `cd`s only).
    s.cwd = matched_cwd or first_cwd
    s.git_branch = matched_git if matched_cwd else first_git
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


def _epoch(ts):
    if not ts:
        return 0
    try:
        return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0


def _subtree_last_epoch(sid, sessions, children, memo):
    """Most-recent activity epoch within this node's subtree (including itself)."""
    if sid in memo:
        return memo[sid]
    best = _epoch(sessions[sid].last)
    for c in children.get(sid, ()):
        v = _subtree_last_epoch(c, sessions, children, memo)
        if v > best:
            best = v
    memo[sid] = best
    return best


def render(sessions, children, roots, filter_str=None, within_seconds=None, now=None):
    memo = {}
    cutoff = None
    if within_seconds:
        cutoff = (now if now is not None else time.time()) - within_seconds

    def keep(sid):
        # Keep a node if it OR any descendant is within the window (preserves lineage).
        return cutoff is None or _subtree_last_epoch(sid, sessions, children, memo) >= cutoff

    def recency(sid):
        return _epoch(sessions[sid].last)

    by_proj = {}
    for sid in roots:
        if not keep(sid):
            continue
        by_proj.setdefault(sessions[sid].cwd or "(unknown)", []).append(sid)

    def proj_recency(proj):
        return max(_subtree_last_epoch(r, sessions, children, memo) for r in by_proj[proj])

    lines = []
    ordered = []
    for proj in sorted(by_proj, key=proj_recency, reverse=True):
        if filter_str and filter_str.lower() not in proj.lower():
            continue
        lines.append("\U0001F4C1 %s" % proj)
        for sid in sorted(by_proj[proj], key=recency, reverse=True):
            _emit(sid, sessions, children, lines, ordered, keep)
        lines.append("")
    return "\n".join(lines).rstrip(), ordered


def _emit(sid, sessions, children, lines, ordered, keep,
          child_prefix="  ", is_root=True, is_last=True):
    s = sessions[sid]
    idx = len(ordered)
    ordered.append(sid)
    if is_root:
        line_prefix = "  "
        next_prefix = "  "
    else:
        line_prefix = child_prefix + ("└─ " if is_last else "├─ ")
        next_prefix = child_prefix + ("   " if is_last else "│  ")
    extra = (" · %s" % s.git_branch) if s.git_branch else ""
    d = fork_depth(s, sessions)
    if d is not None:
        extra += "  ↳forked after %d msg" % d
    lines.append("%s[%d] %s · %s · %dmsg · %s%s"
                 % (line_prefix, idx, s.sid[:8], s.label[:32], s.msgs, _idle(s.last), extra))
    kids = [c for c in children.get(sid, ()) if keep(c)]
    kids.sort(key=lambda c: _epoch(sessions[c].last), reverse=True)
    for i, c in enumerate(kids):
        _emit(c, sessions, children, lines, ordered, keep, next_prefix,
              is_root=False, is_last=(i == len(kids) - 1))


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


_DURATION_RE = re.compile(r"^(\d+)([mhdw])$")
_DURATION_MULT = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_filter_args(tokens):
    """Split CLI tokens into (project_filter, within_seconds).

    A token like 10d / 3h / 2w / 30m sets the time window; everything else
    joins into a project-name substring filter.
    """
    project = []
    within = None
    for tok in tokens:
        m = _DURATION_RE.match(tok.strip())
        if m:
            within = int(m.group(1)) * _DURATION_MULT[m.group(2)]
        else:
            project.append(tok)
    return (" ".join(project).strip() or None, within)


def cmd_render(arg_tokens=None):
    filter_str, within = parse_filter_args(arg_tokens or [])
    sessions = load_sessions()
    owner = build_owner_index(sessions) if _needs_owner(sessions) else None
    children, roots = build_forest(sessions, owner)
    text, ordered = render(sessions, children, roots, filter_str, within)
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
        return cmd_render(argv[2:])
    if cmd == "resume":
        return cmd_resume(argv[2:])
    print("unknown command: %s (use 'render' or 'resume')" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
