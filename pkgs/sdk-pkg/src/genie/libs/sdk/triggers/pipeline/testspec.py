import sys
import argparse
import time
import logging
from ats import aetest
from ats.log.utils import banner
from ats.utils.objects import find, R
from genie.utils.loadattr import str_to_list
from genie.harness.base import Trigger
from genie.libs.sdk.triggers.blitz.blitz import Blitz

from .actions import ActionMeta


log = logging.getLogger(__name__)
# sys.argv - pass in --option to to pyats run.  This will show up ?


class TestSpec(Trigger):
    """Model Pipeline Test Specification."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._blitz = Blitz(*args, **kwargs)
        self.action_runner = ActionRunner()

    def _step_test(self, step, testbed):
        data = self.parameters.get('data', {})
        actions = self.parameters.get('test_actions', {})

        for action in actions:
            name = 'RUN ' + action.get('action', 'unknown')
            with step.start(name.upper()) as test_step:
                self.action_runner.run_banner(action)
                self.action_runner.run_log(action)
                if not self.action_runner.run(action, data, testbed):
                    test_step.failed()

    @aetest.test
    def configure(self, testbed, preconfig=None):
        '''Apply configuration on the devices'''
        return self._blitz._configure(preconfig, testbed)

    @aetest.test
    def validate_configure(self, steps, testbed, validate_preconfig=None):
        '''Validate configuration on the devices'''
        return self._blitz._validate(validate_preconfig, testbed, steps)

    @aetest.test
    def run_pipeline_tests(self, testbed, steps, suites={}):
        """Run test actions defined in Model Pipeline tests."""
        # argparse here to catch sys.argv
        self._step_test(steps, testbed)

    @aetest.test
    def unconfigure(self, testbed, postconfig=None):
        '''remove configuration on the devices'''
        return self._blitz._configure(postconfig, testbed)

    @aetest.test
    def validate_unconfigure(self, steps, testbed, validate_postconfig=None):
        '''Validate unconfiguration on the devices'''
        return self._blitz._validate(validate_postconfig, testbed, steps)


class ActionRunner(metaclass=ActionMeta):

    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.log.setLevel(logging.DEBUG)

    def run(self, action={'action': 'empty'}, params={}, testbed={}):
        name = action.get('action', 'empty')
        if not hasattr(self, name):
            name = 'empty'
        return getattr(self, name)(action, params, testbed)

    def run_banner(self, action):
        if 'banner' in action:
            self.log.info(banner(action['banner']))

    def run_log(self, action):
        if 'log' in action:
            self.log.debug(action['log'])
