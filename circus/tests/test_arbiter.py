import json
import os
import socket
import sys
import unittest

from mock import patch
from tempfile import mkstemp
from time import time
from urlparse import urlparse

from circus.arbiter import Arbiter
from circus.client import CallError, CircusClient, make_message
from circus.plugins import CircusPlugin
from circus.tests.support import TestCircus, poll_for, truncate_file
from circus.util import DEFAULT_ENDPOINT_DEALER, DEFAULT_ENDPOINT_MULTICAST
from circus.watcher import Watcher


_GENERIC = os.path.join(os.path.dirname(__file__), 'generic.py')


class Plugin(CircusPlugin):
    name = 'dummy'

    def __init__(self, *args, **kwargs):
        super(Plugin, self).__init__(*args, **kwargs)
        with open(self.config['file'], 'a+') as f:
            f.write('PLUGIN STARTED')

    def handle_recv(self, data):
        topic, msg = data
        topic_parts = topic.split(".")
        watcher = topic_parts[1]
        action = topic_parts[2]
        with open(self.config['file'], 'a+') as f:
            f.write('%s:%s' % (watcher, action))


class TestTrainer(TestCircus):

    def setUp(self):
        super(TestTrainer, self).setUp()
        dummy_process = 'circus.tests.support.run_process'
        self.test_file = self._run_circus(dummy_process)
        poll_for(self.test_file, 'START')

    def test_numwatchers(self):
        msg = make_message("numwatchers")
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("numwatchers"), 1)

    def test_numprocesses(self):
        msg = make_message("numprocesses")
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("numprocesses"), 1)

    def test_processes(self):
        msg1 = make_message("list", name="test")
        resp = self.cli.call(msg1)
        self.assertEqual(len(resp.get('pids')), 1)

        msg2 = make_message("incr", name="test")
        self.cli.call(msg2)

        resp = self.cli.call(msg1)
        self.assertEqual(len(resp.get('pids')), 2)

        self.cli.send_message("incr", name="test", nb=2)
        resp = self.cli.call(msg1)
        self.assertEqual(len(resp.get('pids')), 4)

    def test_watchers(self):
        if 'TRAVIS' in os.environ:
            return
        resp = self.cli.call(make_message("list"))
        self.assertEqual(resp.get('watchers'), ["test"])

    def _get_cmd(self):
        fd, testfile = mkstemp()
        os.close(fd)
        cmd = '%s %s %s %s' % (
            sys.executable, _GENERIC,
            'circus.tests.support.run_process',
            testfile)

        return cmd

    def _get_cmd_args(self):
        cmd = sys.executable
        args = [_GENERIC, 'circus.tests.support.run_process']
        return cmd, args

    def _get_options(self, **kwargs):
        if 'graceful_timeout' not in kwargs:
            kwargs['graceful_timeout'] = 4
        return kwargs

    def test_add_watcher(self):
        msg = make_message("add", name="test1", cmd=self._get_cmd(),
                           options=self._get_options())
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")

    def test_add_watcher1(self):
        msg = make_message("add", name="test1", cmd=self._get_cmd(),
                           options=self._get_options())
        self.cli.call(msg)
        resp = self.cli.call(make_message("list"))
        self.assertEqual(resp.get('watchers'), ["test", "test1"])

    def test_add_watcher2(self):
        msg = make_message("add", name="test1", cmd=self._get_cmd(),
                           options=self._get_options())
        self.cli.call(msg)
        resp = self.cli.call(make_message("numwatchers"))
        self.assertEqual(resp.get("numwatchers"), 2)

    def test_add_watcher3(self):
        msg = make_message("add", name="test1", cmd=self._get_cmd(),
                           options=self._get_options())
        self.cli.call(msg)
        resp = self.cli.call(msg)
        self.assertTrue(resp.get('status'), 'error')

    def test_add_watcher4(self):
        cmd, args = self._get_cmd_args()
        msg = make_message("add", name="test1", cmd=cmd, args=args,
                           options=self._get_options())
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")

    def test_add_watcher5(self):
        cmd, args = self._get_cmd_args()
        msg = make_message("add", name="test1", cmd=cmd, args=args,
                           options=self._get_options())
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")
        resp = self.cli.call(make_message("start", name="test1"))
        self.assertEqual(resp.get("status"), "ok")
        resp = self.cli.call(make_message("status", name="test1"))
        self.assertEqual(resp.get("status"), "active")

    def test_add_watcher6(self):
        cmd, args = self._get_cmd_args()
        msg = make_message("add", name="test1", cmd=cmd, args=args,
                           start=True, options=self._get_options())
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")

        resp = self.cli.call(make_message("status", name="test1"))
        self.assertEqual(resp.get("status"), "active")

    def test_add_watcher7(self):
        cmd, args = self._get_cmd_args()
        msg = make_message("add", name="test1", cmd=cmd, args=args, start=True,
                           options=self._get_options(flapping_window=100))
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")

        resp = self.cli.call(make_message("status", name="test1"))
        self.assertEqual(resp.get("status"), "active")

        resp = self.cli.call(make_message("options", name="test1"))
        options = resp.get('options', {})
        self.assertEqual(options.get("flapping_window"), 100)

    def test_rm_watcher(self):
        msg = make_message("add", name="test1", cmd=self._get_cmd(),
                           options=self._get_options())
        self.cli.call(msg)
        msg = make_message("rm", name="test1")
        self.cli.call(msg)
        resp = self.cli.call(make_message("numwatchers"))
        self.assertEqual(resp.get("numwatchers"), 1)

    def _test_stop(self):
        resp = self.cli.call(make_message("quit"))
        self.assertEqual(resp.get("status"), "ok")
        self.assertRaises(CallError, self.cli.call, make_message("list"))

        self._stop_runners()
        cli = CircusClient()
        dummy_process = 'circus.tests.support.run_process'
        self.test_file = self._run_circus(dummy_process)
        msg = make_message("numprocesses")
        resp = cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")

    def test_reload(self):
        resp = self.cli.call(make_message("reload"))
        self.assertEqual(resp.get("status"), "ok")

    def test_reload1(self):
        msg1 = make_message("list", name="test")
        resp = self.cli.call(msg1)
        processes1 = resp.get('pids')

        truncate_file(self.test_file)  # clean slate
        self.cli.call(make_message("reload"))
        self.assertTrue(poll_for(self.test_file, 'START'))  # restarted

        msg2 = make_message("list", name="test")
        resp = self.cli.call(msg2)
        processes2 = resp.get('pids')

        self.assertNotEqual(processes1, processes2)

    def test_reload2(self):
        msg1 = make_message("list", name="test")
        resp = self.cli.call(msg1)
        processes1 = resp.get('pids')
        self.assertEqual(len(processes1), 1)

        truncate_file(self.test_file)  # clean slate
        self.cli.call(make_message("reload"))
        self.assertTrue(poll_for(self.test_file, 'START'))  # restarted

        make_message("list", name="test")
        resp = self.cli.call(msg1)

        processes2 = resp.get('pids')
        self.assertEqual(len(processes2), 1)
        self.assertNotEqual(processes1[0], processes2[0])

    def test_stop_watchers(self):
        if 'TRAVIS' in os.environ:
            return
        resp = self.cli.call(make_message("stop"))
        self.assertEqual(resp.get("status"), "ok")

    def test_stop_watchers1(self):
        if 'TRAVIS' in os.environ:
            return
        self.cli.call(make_message("stop"))
        resp = self.cli.call(make_message("status", name="test"))
        self.assertEqual(resp.get("status"), "stopped")

    def test_stop_watchers2(self):
        if 'TRAVIS' in os.environ:
            return
        self.cli.call(make_message("stop", name="test"))
        resp = self.cli.call(make_message("status", name="test"))
        self.assertEqual(resp.get('status'), "stopped")

    def test_stop_watchers3(self):
        if 'TRAVIS' in os.environ:
            return
        cmd, args = self._get_cmd_args()
        msg = make_message("add", name="test1", cmd=cmd, args=args,
                           options=self._get_options())
        resp = self.cli.call(msg)
        self.assertEqual(resp.get("status"), "ok")
        resp = self.cli.call(make_message("start", name="test1"))
        self.assertEqual(resp.get("status"), "ok")

        self.cli.call(make_message("stop", name="test1"))
        resp = self.cli.call(make_message("status", name="test1"))
        self.assertEqual(resp.get('status'), "stopped")

        resp = self.cli.call(make_message("status", name="test"))
        self.assertEqual(resp.get('status'), "active")

    def test_plugins(self):
        # killing the setUp runner
        self._stop_runners()
        self.cli.stop()

        fd, datafile = mkstemp()
        os.close(fd)

        # setting up a circusd with a plugin
        dummy_process = 'circus.tests.support.run_process'
        plugin = 'circus.tests.test_arbiter.Plugin'
        plugins = [{'use': plugin, 'file': datafile}]
        self._run_circus(dummy_process, plugins=plugins)

        # doing a few operations
        def nb_processes():
            return len(cli.send_message('list', name='test').get('pids'))

        def incr_processes():
            return cli.send_message('incr', name='test')

        # wait for the plugin to be started
        self.assertTrue(poll_for(datafile, 'PLUGIN STARTED'))

        cli = CircusClient()
        self.assertEqual(nb_processes(), 1)
        incr_processes()
        self.assertEqual(nb_processes(), 2)
        # wait for the plugin to receive the signal
        self.assertTrue(poll_for(datafile, 'test:spawn'))
        truncate_file(datafile)
        incr_processes()
        self.assertEqual(nb_processes(), 3)
        # wait for the plugin to receive the signal
        self.assertTrue(poll_for(datafile, 'test:spawn'))

    def test_singleton(self):
        self._stop_runners()

        dummy_process = 'circus.tests.support.run_process'
        self._run_circus(dummy_process, singleton=True)
        cli = CircusClient()

        # adding more than one process should fail
        res = cli.send_message('incr', name='test')
        self.assertEqual(res['numprocesses'], 1)

    def test_udp_discovery(self):
        """test_udp_discovery: Test that when the circusd answer UDP call.

        """
        if 'TRAVIS' in os.environ:
            return
        self._stop_runners()

        dummy_process = 'circus.tests.support.run_process'
        self._run_circus(dummy_process)

        ANY = '0.0.0.0'

        multicast_addr, multicast_port = urlparse(DEFAULT_ENDPOINT_MULTICAST)\
            .netloc.split(':')

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                             socket.IPPROTO_UDP)
        sock.bind((ANY, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        sock.sendto(json.dumps(''),
                    (multicast_addr, int(multicast_port)))

        timer = time()
        resp = False
        endpoints = []
        while time() - timer < 10:
            data, address = sock.recvfrom(1024)
            data = json.loads(data)
            endpoint = data.get('endpoint', "")

            if endpoint == DEFAULT_ENDPOINT_DEALER:
                resp = True
                break

            endpoints.append(endpoint)

        if not resp:
            print endpoints

        self.assertTrue(resp)


class MockWatcher(Watcher):

    def start(self):
        self.started = True


class TestArbiter(unittest.TestCase):
    """
    Unit tests for the arbiter class to codify requirements within
    behavior.
    """
    def test_start_watcher(self):
        watcher = MockWatcher(name='foo', cmd='serve', priority=1)
        arbiter = Arbiter([], None, None)
        arbiter.start_watcher(watcher)
        self.assertTrue(watcher.started)

    def test_start_watchers_with_autostart(self):
        watcher = MockWatcher(name='foo', cmd='serve', priority=1,
                              autostart=False)
        arbiter = Arbiter([], None, None)
        arbiter.start_watcher(watcher)
        self.assertFalse(getattr(watcher, 'started', False))

    def test_start_watchers_warmup_delay(self):
        watcher = MockWatcher(name='foo', cmd='serve', priority=1)
        arbiter = Arbiter([], None, None, warmup_delay=10)
        with patch('circus.arbiter.sleep') as mock_sleep:
            arbiter.start_watcher(watcher)
            mock_sleep.assert_called_with(10)

        # now make sure we don't sleep when there is a autostart
        watcher = MockWatcher(name='foo', cmd='serve', priority=1,
                              autostart=False)
        with patch('circus.arbiter.sleep') as mock_sleep:
            arbiter.start_watcher(watcher)
            assert not mock_sleep.called
