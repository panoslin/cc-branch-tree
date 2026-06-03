"""Unit tests for the cc-branch-tree engine (stdlib unittest, zero deps)."""
import os
import sys
import io
import contextlib
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

# Point the engine at fixtures + a throwaway data dir BEFORE importing it.
FIX = os.path.join(HERE, "fixtures", "projects")
os.environ["CC_PROJECTS_DIR"] = FIX
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp(prefix="ccbt-test-")
os.environ["CC_NO_CLIPBOARD"] = "1"  # never touch the real clipboard during tests

import cc_tree  # noqa: E402


def fpath(proj, sid):
    return os.path.join(FIX, proj, sid + ".jsonl")


class TestParse(unittest.TestCase):
    def test_root(self):
        s = cc_tree.parse_transcript(fpath("proj1", "root"))
        self.assertIsNone(s.forked_from_sid)
        self.assertEqual(s.label, "Root Session")
        self.assertEqual(s.msgs, 2)
        self.assertEqual(s.cwd, "/work/proj1")
        self.assertEqual(s.git_branch, "main")

    def test_child(self):
        s = cc_tree.parse_transcript(fpath("proj1", "child"))
        self.assertEqual(s.forked_from_sid, "root")
        self.assertTrue({"a1", "a2"} <= s.inherited_uuids)
        self.assertEqual(s.msgs, 3)
        self.assertEqual(s.label, "Child Branch")
        self.assertEqual(s.inherited_in_order[-1], "a2")

    def test_latest_title_wins(self):
        s = cc_tree.parse_transcript(fpath("proj1", "renamed"))
        self.assertEqual(s.label, "New Name")

    def test_caveat_stripped_from_preview(self):
        s = cc_tree.parse_transcript(fpath("proj2", "caveat"))
        self.assertEqual(s.label, "Real user question about X")

    def test_cwd_picks_project_root_not_subdir(self):
        # First cwd is a subdir; the cwd matching the folder encoding must win.
        s = cc_tree.parse_transcript(fpath("-work-projx", "cwdpick"))
        self.assertEqual(s.cwd, "/work/projx")

    def test_command_invocation_label(self):
        # First message is a /command invocation -> label by command name, not body.
        s = cc_tree.parse_transcript(fpath("proj2", "cmdrun"))
        self.assertEqual(s.label, "/deploy")


class TestForest(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.owner = cc_tree.build_owner_index(self.sessions)
        self.children, self.roots = cc_tree.build_forest(self.sessions, self.owner)

    def test_nesting(self):
        self.assertEqual(set(self.children.get("root", [])), {"child", "sib"})
        self.assertEqual(set(self.children.get("child", [])), {"grand"})
        for r in ("root", "solo", "orphan"):
            self.assertIn(r, self.roots)

    def test_sibling_not_nested_containment_trap(self):
        # sib's inherited set is a subset of grand's uuids, but the parent must be root.
        self.assertTrue(self.sessions["sib"].inherited_uuids <= self.sessions["grand"].all_uuids)
        self.assertEqual(
            cc_tree.immediate_parent(self.sessions["sib"], self.sessions, self.owner), "root"
        )

    def test_authorship_invariant(self):
        # F5 (forkedFrom.sessionId) must equal F6 (author of last inherited msg) when parent exists.
        for sid, s in self.sessions.items():
            if s.forked_from_sid in self.sessions and s.inherited_in_order:
                self.assertEqual(
                    self.owner.get(s.inherited_in_order[-1]),
                    s.forked_from_sid,
                    f"{sid}: authorship != forkedFrom",
                )

    def test_orphan_is_root(self):
        self.assertIsNone(
            cc_tree.immediate_parent(self.sessions["orphan"], self.sessions, self.owner)
        )


class TestRenderResolve(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.children, self.roots = cc_tree.build_forest(
            self.sessions, cc_tree.build_owner_index(self.sessions)
        )
        self.text, self.ordered = cc_tree.render(self.sessions, self.children, self.roots)
        cc_tree.write_last_tree(self.ordered, self.sessions)

    def test_depth_first_order(self):
        i = self.ordered.index
        # parent always precedes its own descendants (depth-first)
        self.assertLess(i("root"), i("child"))
        self.assertLess(i("child"), i("grand"))
        self.assertLess(i("root"), i("sib"))

    def test_siblings_sorted_recent_first(self):
        # sib (last 00:03) is more recent than child (last 00:02) -> sib ranks first
        self.assertLess(self.ordered.index("sib"), self.ordered.index("child"))

    def test_indent_grand_under_child(self):
        lines = self.text.splitlines()
        cl = next(l for l in lines if "Child Branch" in l)
        gl = next(l for l in lines if "grandchild question" in l)
        # grand's label sits further right (deeper tree prefix) than child's
        self.assertGreater(gl.index("grandchild question"), cl.index("Child Branch"))

    def test_columns_drop_msg_and_git(self):
        line = next(l for l in self.text.splitlines() if "solo first message" in l)
        self.assertNotIn("msg", line)   # message-count column removed
        self.assertNotIn("dev", line)   # git-branch column removed

    def test_branch_count_shown(self):
        self.assertIn("⑂", self.text)   # nodes with children show ⑂N

    def test_full_name_not_truncated(self):
        title = "This is a very long session title that exceeds thirty-four characters easily"
        self.assertIn(title, self.text)      # shown in full
        self.assertNotIn("…", self.text)     # no truncation ellipsis anywhere

    def test_resolve(self):
        ri = self.ordered.index("root")
        self.assertEqual(cc_tree.resolve(str(ri), self.sessions)[0], "root")
        self.assertEqual(cc_tree.resolve("chi", self.sessions)[0], "child")
        self.assertEqual(cc_tree.resolve("Branch", self.sessions)[0], "child")
        self.assertIsNone(cc_tree.resolve("zzz-nomatch", self.sessions))

    def test_connectors(self):
        def line(sid):
            tag = "[%d]" % self.ordered.index(sid)
            return next(l for l in self.text.splitlines() if tag in l)
        # whichever of root's two children renders last gets └─, the other ├─
        kids = sorted(("child", "sib"), key=self.ordered.index)
        self.assertIn("├─", line(kids[0]))
        self.assertIn("└─", line(kids[-1]))


class TestCLI(unittest.TestCase):
    def test_resume_prints_command(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cc_tree.main(["cc_tree.py", "resume", "root"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("claude --resume root", out)
        self.assertIn('cd "/work/proj1"', out)

    def test_clipboard_guarded_in_tests(self):
        self.assertFalse(cc_tree._copy_to_clipboard("x"))   # CC_NO_CLIPBOARD is set


class TestFilter(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.children, self.roots = cc_tree.build_forest(
            self.sessions, cc_tree.build_owner_index(self.sessions))

    def test_parse_filter_args(self):
        self.assertEqual(cc_tree.parse_filter_args(["10d"]), (None, 10 * 86400, False))
        self.assertEqual(cc_tree.parse_filter_args(["30m"]), (None, 30 * 60, False))
        self.assertEqual(cc_tree.parse_filter_args(["所有笔记"]), ("所有笔记", None, False))
        self.assertEqual(cc_tree.parse_filter_args(["EB1", "2w"]), ("EB1", 2 * 604800, False))
        self.assertEqual(cc_tree.parse_filter_args(["all"]), (None, None, True))
        self.assertEqual(cc_tree.parse_filter_args(["10d", "all"]), (None, 10 * 86400, True))
        self.assertEqual(cc_tree.parse_filter_args([]), (None, None, False))

    def test_time_window_keeps_recent_and_ancestors(self):
        now = cc_tree._epoch("2026-06-01T00:06:00")  # 2-min window -> cutoff 00:04
        _, ordered = cc_tree.render(
            self.sessions, self.children, self.roots, within_seconds=120, now=now)
        for keep in ("root", "child", "grand"):   # grand recent; root+child kept as ancestors
            self.assertIn(keep, ordered)
        for drop in ("sib", "orphan", "solo", "caveat", "cwdpick"):
            self.assertNotIn(drop, ordered)

    def test_command_sessions_auto_hidden(self):
        _, ordered = cc_tree.render(self.sessions, self.children, self.roots)
        self.assertNotIn("cmdrun", ordered)        # /deploy session auto-hidden by default
        _, all_ordered = cc_tree.render(self.sessions, self.children, self.roots, show_all=True)
        self.assertIn("cmdrun", all_ordered)        # 'all' reveals it

    def test_view_persistence(self):
        path = cc_tree._view_path()
        try:
            cc_tree.save_view("proj", 864000, True)
            self.assertEqual(cc_tree.load_view(), ("proj", 864000, True))
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestHidden(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.children, self.roots = cc_tree.build_forest(
            self.sessions, cc_tree.build_owner_index(self.sessions))

    def test_hidden_excluded_children_reparented(self):
        _, ordered = cc_tree.render(self.sessions, self.children, self.roots, hidden={"child"})
        self.assertNotIn("child", ordered)   # the hidden node is gone
        self.assertIn("grand", ordered)      # but its child re-parents to root and stays
        self.assertIn("root", ordered)

    def test_hide_node_promotes_descendants(self):
        _, ordered = cc_tree.render(self.sessions, self.children, self.roots, hidden={"root"})
        self.assertNotIn("root", ordered)
        for s in ("child", "grand", "sib"):
            self.assertIn(s, ordered)

    def test_hidden_footer_has_restore_hint(self):
        text, _ = cc_tree.render(self.sessions, self.children, self.roots, hidden={"child"})
        self.assertIn("hidden (1)", text)
        self.assertIn("unhide", text)

    def test_load_save_hidden_roundtrip(self):
        path = cc_tree._hidden_path()
        try:
            cc_tree.save_hidden({"aaa", "bbb"})
            self.assertEqual(cc_tree.load_hidden(), {"aaa", "bbb"})
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_hide_cascades_to_descendants(self):
        path = cc_tree._hidden_path()
        try:
            cc_tree.save_hidden(set())
            with contextlib.redirect_stdout(io.StringIO()):
                cc_tree.cmd_hide(["root"])   # root has child->grand and sib
            self.assertEqual(cc_tree.load_hidden(), {"root", "child", "grand", "sib"})
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_unhide_cascades_to_descendants(self):
        path = cc_tree._hidden_path()
        try:
            cc_tree.save_hidden({"root", "child", "grand", "sib"})
            with contextlib.redirect_stdout(io.StringIO()):
                cc_tree.cmd_unhide(["root"])
            self.assertEqual(cc_tree.load_hidden(), set())
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_hide_renders_updated_tree(self):
        hp, vp = cc_tree._hidden_path(), cc_tree._view_path()
        try:
            cc_tree.save_hidden(set())
            if os.path.exists(vp):
                os.remove(vp)                    # no saved view -> default render
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cc_tree.cmd_hide(["sib"])
            out = buf.getvalue()
            self.assertIn("Hidden", out)         # confirmation line
            self.assertIn("\U0001F4C1", out)     # the updated tree is printed after it
        finally:
            for p in (hp, vp):
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
