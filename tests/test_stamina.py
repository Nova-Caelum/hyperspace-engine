"""Regression coverage for attached-session stamina and resumable pause."""
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE.parents[1] / 'bin' if HERE.name == 'framework' else HERE.parent / 'bin'
sys.path.insert(0, str(BIN_DIR))
import loop_state
import loop_terminal

class StaminaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = loop_state.LoopState.init(goal_slug='example', workspace=self.tmp.name, original_input='Build')

    def used(self):
        return loop_state.LoopState.load(self.state.path).data['budget']['stamina_blocks']['used']

    def test_unrelated_startup_and_compaction_do_not_write(self):
        before = self.state.path.read_bytes()
        for event in ('startup', 'compact', 'resume', 'clear'):
            for session in ('unrelated', None):
                self.assertEqual(0, loop_state.bump(self.state, event, session))
        self.assertEqual(before, self.state.path.read_bytes())

    def test_new_session_once_plus_each_compaction(self):
        self.assertEqual(1, loop_state.attach_session(self.state, 'a'))
        self.assertEqual(0, loop_state.attach_session(self.state, 'a'))
        for event in ('startup', 'startup', 'resume', 'clear'):
            self.assertEqual(0, loop_state.bump(self.state, event, 'a'))
        self.assertEqual(2, loop_state.bump(self.state, 'compact', 'a'))
        self.assertEqual(3, loop_state.bump(self.state, 'compact', 'a'))
        self.assertEqual(4, loop_state.attach_session(self.state, 'b'))
        self.assertEqual(4, self.used())

    def test_attachment_is_per_run(self):
        other = loop_state.LoopState.init(goal_slug='other', workspace=self.tmp.name, original_input='Other')
        loop_state.attach_session(self.state, 'a')
        self.assertEqual(0, loop_state.bump(other, 'compact', 'a'))
        self.assertEqual(0, other.data['budget']['stamina_blocks']['used'])

    def test_blank_id_rejected(self):
        with self.assertRaises(ValueError):
            loop_state.attach_session(self.state, ' ')

    def test_legacy_totals_preserved_not_converted(self):
        data = self.state.data
        data['budget'].pop('stamina_blocks')
        data.pop('attached_sessions')
        data.pop('project_link')
        old = {'fresh_sessions': {'cap': 1, 'used': 62}, 'compactions': {'cap': 1, 'used': 17}}
        data['budget'].update(old)
        self.state.path.write_text(json.dumps(data))
        original = self.state.path.read_bytes()
        loaded = loop_state.LoopState.load(self.state.path)
        self.assertEqual(original, self.state.path.read_bytes())
        self.assertEqual(old, loaded.data['legacy_budget'])
        self.assertEqual(0, loaded.data['budget']['stamina_blocks']['used'])
        loop_state.attach_session(loaded, 'new')
        again = loop_state.LoopState.load(self.state.path)
        self.assertEqual(old, again.data['legacy_budget'])
        self.assertEqual(1, self.used())
        self.assertNotIn('fresh_sessions', again.data['budget'])

    def test_cap_unset_until_owner_chooses_and_crossing_only_notifies(self):
        self.assertIsNone(self.state.data['budget']['stamina_blocks']['cap'])
        loop_state.attach_session(self.state, 'a')
        self.assertEqual([], loop_state.notify(self.state))
        self.state.data['budget']['stamina_blocks']['cap'] = 1
        loop_state.bump(self.state, 'compact', 'a')
        self.assertIn('stamina_blocks: 2>1', loop_state.notify(self.state)[0])
        self.assertEqual('framing', self.state.data['status'])

    def test_terminal_freezes_accounting(self):
        loop_state.attach_session(self.state, 'a')
        for status in loop_terminal.LEGITIMATE_TERMINAL:
            self.state.data['status'] = status
            self.state.save()
            self.assertEqual(0, loop_state.attach_session(self.state, 'b'))
            self.assertEqual(0, loop_state.bump(self.state, 'compact', 'a'))
        self.assertEqual(1, self.used())

    def test_pause_retains_node_gates_and_resumes_prior_status(self):
        loop_state.attach_session(self.state, 'a')
        self.state.set_node('executing')
        loop_state.pause(self.state)
        loop_state.pause(self.state)
        self.assertEqual('paused', self.state.data['status'])
        self.assertIsNone(loop_terminal.terminal_route(self.state))
        self.assertEqual(0, loop_state.bump(self.state, 'compact', 'a'))
        self.assertEqual(0, loop_state.attach_session(self.state, 'b'))
        with self.assertRaises(ValueError):
            self.state.set_node('understanding')
        with self.assertRaises(ValueError):
            loop_state.gate_pass(self.state, 'executing', [], 'tester')
        loaded = loop_state.LoopState.load(self.state.path)
        loop_state.resume(loaded)
        self.assertEqual('executing', loaded.data['status'])
        self.assertEqual('executing', loaded.data['current_node'])

    def test_draft_exit_requires_project_link(self):
        with self.assertRaisesRegex(ValueError, 'link-project'):
            loop_state.gate_pass(self.state, 'specifying', [], 'tester')
        loop_state.link_project(self.state, 'project-a', ['module-b'])
        loop_state.gate_pass(self.state, 'specifying', [], 'tester')
        self.assertEqual({'project':'project-a','modules':['module-b']}, loop_state.LoopState.load(self.state.path).data['project_link'])

    def test_windows_transient_share_lock_retries_atomic_replace(self):
        error = PermissionError('sharing denied')
        error.winerror = 32
        with mock.patch.object(loop_state.os, 'name', 'nt'), \
             mock.patch.object(loop_state.os, 'replace', side_effect=[error, None]) as replace, \
             mock.patch.object(loop_state.time, 'sleep') as sleep:
            loop_state._replace_state_file('source', 'destination')
        self.assertEqual(2, replace.call_count)
        sleep.assert_called_once_with(0.05)

    def test_windows_persistent_share_lock_fails_at_deadline(self):
        error = PermissionError('access denied')
        error.winerror = 5
        with mock.patch.object(loop_state.os, 'name', 'nt'), \
             mock.patch.object(loop_state.os, 'replace', side_effect=error) as replace, \
             mock.patch.object(loop_state.time, 'monotonic', side_effect=[0, 5]):
            with self.assertRaises(PermissionError):
                loop_state._replace_state_file('source', 'destination')
        replace.assert_called_once()

    def test_non_windows_permission_error_is_not_retried(self):
        with mock.patch.object(loop_state.os, 'name', 'posix'), \
             mock.patch.object(loop_state.os, 'replace', side_effect=PermissionError) as replace:
            with self.assertRaises(PermissionError):
                loop_state._replace_state_file('source', 'destination')
        replace.assert_called_once()

    def test_concurrent_cli_attachments_preserve_every_session(self):
        processes = [subprocess.Popen(
            [sys.executable, str(BIN_DIR/'loop_state.py'), 'attach-session',
             str(self.state.path), '--session-id', f'session-{i}'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for i in range(8)]
        for process in processes:
            out, err = process.communicate(timeout=20)
            self.assertEqual(0, process.returncode, err)
        data = loop_state.LoopState.load(self.state.path).data
        self.assertEqual(8, self.used())
        self.assertEqual({f'session-{i}' for i in range(8)}, set(data['attached_sessions']))

    def test_cli_attach_compact_pause_resume(self):
        for args in [('attach-session','--session-id','a'), ('bump','--event','compact','--session-id','a'), ('pause',), ('resume',)]:
            result=subprocess.run([sys.executable,str(BIN_DIR/'loop_state.py'),args[0],str(self.state.path),*args[1:]],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(2,self.used())

if __name__ == '__main__':
    unittest.main()
