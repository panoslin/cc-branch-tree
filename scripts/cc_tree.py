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


def _apply_hidden(sessions, children, roots, hidden):
    """Drop hidden sessions; re-parent their children to the nearest visible ancestor."""
    parent = {}
    for p, kids in children.items():
        for k in kids:
            parent[k] = p
    vchildren = {}
    vroots = []
    for sid in sessions:
        if sid in hidden:
            continue
        p = parent.get(sid)
        while p is not None and p in hidden:
            p = parent.get(p)
        if p is None:
            vroots.append(sid)
        else:
            vchildren.setdefault(p, []).append(sid)
    return vchildren, vroots


def _is_command_session(s):
    """True if the session's first message was a slash-command invocation (label '/foo')."""
    return bool(s.label) and s.label.startswith("/")


def render(sessions, children, roots, filter_str=None, within_seconds=None, now=None,
           hidden=None, show_all=False):
    user_hidden = set(hidden or ())
    cmd_hidden = set() if show_all else {sid for sid, s in sessions.items()
                                         if _is_command_session(s)}
    effective = user_hidden | cmd_hidden
    if effective:
        children, roots = _apply_hidden(sessions, children, roots, effective)
    memo = {}
    cutoff = None
    if within_seconds:
        cutoff = (now if now is not None else time.time()) - within_seconds

    def keep(sid):
        # Keep a node if it OR any descendant is within the window (preserves lineage).
        return cutoff is None or _subtree_last_epoch(sid, sessions, children, memo) >= cutoff

    def recency(sid):
        return _epoch(sessions[sid].last)

    def proj_recency(group):
        return max(_subtree_last_epoch(r, sessions, children, memo) for r in group)

    by_proj = {}
    for sid in roots:
        if not keep(sid):
            continue
        by_proj.setdefault(sessions[sid].cwd or "(unknown)", []).append(sid)

    ordered = []
    rows = []

    def collect(sid, prefix, is_root, is_last, proj):
        s = sessions[sid]
        ordered.append(sid)
        if is_root:
            tree, child_pref = "", ""
        else:
            tree = prefix + ("└─ " if is_last else "├─ ")
            child_pref = prefix + ("   " if is_last else "│  ")
        kids = [c for c in children.get(sid, ()) if keep(c)]
        kids.sort(key=recency, reverse=True)
        rows.append({"idx": len(ordered) - 1, "sid": s.sid[:8], "prefix": tree,
                     "label": s.label or "(untitled)", "time": _idle(s.last),
                     "branches": len(kids), "proj": proj})
        for i, c in enumerate(kids):
            collect(c, child_pref, False, i == len(kids) - 1, proj)

    for proj in sorted(by_proj, key=lambda p: proj_recency(by_proj[p]), reverse=True):
        if filter_str and filter_str.lower() not in proj.lower():
            continue
        for sid in sorted(by_proj[proj], key=recency, reverse=True):
            collect(sid, "", True, True, proj)

    lines = []
    if rows:
        # Aligned left columns: index, session-id, time. The full name (with tree
        # prefix) is last so it can be any length without breaking alignment.
        idx_w = max(len("[%d]" % r["idx"]) for r in rows)
        time_w = max(len(r["time"]) for r in rows)
        cur = None
        for r in rows:
            if r["proj"] != cur:
                if lines:
                    lines.append("")
                lines.append("\U0001F4C1 %s" % r["proj"])
                cur = r["proj"]
            idx_s = ("[%d]" % r["idx"]).rjust(idx_w)
            branch = ("  ⑂%d" % r["branches"]) if r["branches"] else ""
            line = "  %s  %s  %s  %s%s" % (idx_s, r["sid"], r["time"].rjust(time_w),
                                           r["prefix"] + r["label"], branch)
            lines.append(line.rstrip())

    text = "\n".join(lines).rstrip()
    notes = []
    uh = sorted(h for h in user_hidden if h in sessions)
    if uh:
        preview = ", ".join("%s %s" % (h[:8], sessions[h].label[:18]) for h in uh[:8])
        more = " …" if len(uh) > 8 else ""
        notes.append("· hidden (%d): %s%s  —  /cc-branch-tree:unhide <id|all> to restore"
                     % (len(uh), preview, more))
    auto = len(cmd_hidden - user_hidden)
    if auto:
        notes.append("· %d command session(s) auto-hidden  —  /cc-branch-tree:tree all to show"
                     % auto)
    if notes:
        text += "\n\n" + "\n".join(notes)
    return text, ordered


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


def _hidden_path():
    return os.path.join(data_dir(), "hidden.json")


def load_hidden():
    try:
        with open(_hidden_path(), encoding="utf-8") as fh:
            return set(json.load(fh))
    except (OSError, json.JSONDecodeError):
        return set()


def save_hidden(hidden):
    with open(_hidden_path(), "w", encoding="utf-8") as fh:
        json.dump(sorted(hidden), fh)


def _view_path():
    return os.path.join(data_dir(), "last_view.json")


def save_view(filter_str, within, show_all):
    with open(_view_path(), "w", encoding="utf-8") as fh:
        json.dump({"filter": filter_str, "within": within, "show_all": show_all}, fh)


def load_view():
    """Return (filter_str, within_seconds, show_all) from the last /tree, or defaults."""
    try:
        with open(_view_path(), encoding="utf-8") as fh:
            v = json.load(fh)
        return v.get("filter"), v.get("within"), bool(v.get("show_all"))
    except (OSError, json.JSONDecodeError):
        return None, None, False


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
    """Split CLI tokens into (project_filter, within_seconds, show_all).

    'all' also shows command-runner sessions; a token like 10d/3h/2w/30m sets the
    time window; everything else joins into a project-name substring filter.
    """
    project = []
    within = None
    show_all = False
    for tok in tokens:
        t = tok.strip()
        if t.lower() == "all":
            show_all = True
        elif _DURATION_RE.match(t):
            m = _DURATION_RE.match(t)
            within = int(m.group(1)) * _DURATION_MULT[m.group(2)]
        else:
            project.append(tok)
    return (" ".join(project).strip() or None, within, show_all)


def _print_tree(sessions, children, roots, hidden=None, filter_str=None, within=None, show_all=False):
    text, ordered = render(sessions, children, roots, filter_str, within,
                           hidden=hidden, show_all=show_all)
    write_last_tree(ordered, sessions)
    print(text if text else "No sessions found.")


def cmd_render(arg_tokens=None):
    filter_str, within, show_all = parse_filter_args(arg_tokens or [])
    save_view(filter_str, within, show_all)
    sessions = load_sessions()
    owner = build_owner_index(sessions) if _needs_owner(sessions) else None
    children, roots = build_forest(sessions, owner)
    _print_tree(sessions, children, roots, load_hidden(), filter_str, within, show_all)
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


def _descendants(sid, children, acc):
    for c in children.get(sid, ()):
        if c not in acc:
            acc.add(c)
            _descendants(c, children, acc)
    return acc


def cmd_hide(selectors):
    sessions = load_sessions()
    owner = build_owner_index(sessions) if _needs_owner(sessions) else None
    children, roots = build_forest(sessions, owner)
    hidden = load_hidden()
    added, missing = [], []
    for sel in selectors:
        hit = resolve(sel, sessions)
        if not hit:
            missing.append(sel)
            continue
        for t in {hit[0]} | _descendants(hit[0], children, set()):  # node + its branches
            if t not in hidden:
                hidden.add(t)
                added.append(t)
    save_hidden(hidden)
    out = "Hidden %d session(s) from /tree" % len(added)
    if added:
        out += ": " + ", ".join(s[:8] for s in added)
    if missing:
        out += " | no match: " + ", ".join(missing)
    print(out)
    print()
    f, w, sa = load_view()
    _print_tree(sessions, children, roots, hidden, f, w, sa)   # re-render the same view
    return 0


def cmd_unhide(selectors):
    sessions = load_sessions()
    owner = build_owner_index(sessions) if _needs_owner(sessions) else None
    children, roots = build_forest(sessions, owner)
    hidden = load_hidden()
    removed = []
    if selectors and selectors[0].lower() == "all":
        removed = sorted(hidden)
        hidden = set()
    else:
        for sel in selectors:
            hit = resolve(sel, sessions)
            targets = ({hit[0]} | _descendants(hit[0], children, set())) if hit else set()
            for h in list(hidden):
                if h in targets or h.startswith(sel):
                    hidden.discard(h)
                    removed.append(h)
    save_hidden(hidden)
    out = "Restored %d session(s)" % len(removed)
    if removed:
        out += ": " + ", ".join(s[:8] for s in removed)
    print(out)
    print()
    f, w, sa = load_view()
    _print_tree(sessions, children, roots, hidden, f, w, sa)   # re-render the same view
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "render"
    if cmd == "render":
        return cmd_render(argv[2:])
    if cmd == "resume":
        return cmd_resume(argv[2:])
    if cmd == "hide":
        return cmd_hide(argv[2:])
    if cmd == "unhide":
        return cmd_unhide(argv[2:])
    print("unknown command: %s (use 'render' or 'resume')" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
