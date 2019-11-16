import time
import logging
from ats import aetest
from ats.utils.objects import find, R
from genie.utils.loadattr import str_to_list
from genie.harness.base import Trigger

from .actions import ActionMeta


log = logging.getLogger(__name__)
# sys.argv - pass in --option to to pyats run.  This will show up ?


class TestSpec(Trigger):
    """Model Pipeline Test Specification."""

    def __init__(self, *args, **kwargs):
        self.action_runner = ActionRunner()
        super().__init__(*args, **kwargs)

    def _run_actions(self, actions, testbed):
        pass_cnt = 0
        fail_cnt = 0
        data = self.parameters.get('data', {})

        for action in actions:
            self.action_runner.run(action, data, testbed)
            pass_cnt += 1
        return pass_cnt, fail_cnt

    def _step_test(self, step, test, testbed):
        with step.start(test) as test_step:
            actions = self.parameters.get(test, {})
            pass_results, fail_results = self._run_actions(
                actions.get('test_actions', []),
                testbed
            )
            if fail_results:
                test_step.failed('{0} failed'.format(fail_results))
            if pass_results:
                test_step.passed('{0} failed'.format(pass_results))

    @aetest.test
    def run_pipeline_tests(self, testbed, steps, suites={}):
        """Run test actions defined in Model Pipeline tests."""
        # argparse here to catch sys.argv
        if suites:
            for name, tests in suites.items():
                with steps.start('Test Suite {0}'.format(name)) as step:
                    for test in tests:
                        self._step_test(step, test, testbed)
        else:
            tests = [test for test in self.parameters.keys() if test != 'data']
            for test in tests:
                self._step_test(steps, test, testbed)


class ActionRunner(metaclass=ActionMeta):

    def run(self, action={'action': 'empty'}, params={}, testbed={}):
        name = action.get('action', 'empty')
        if not hasattr(self, name):
            name = 'empty'
        return getattr(self, name)(action, params, testbed)
