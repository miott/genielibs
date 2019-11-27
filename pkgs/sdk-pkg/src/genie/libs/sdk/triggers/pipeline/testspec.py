import sys
import argparse
import time
import logging
import yaml
import yamlordereddictloader
from jinja2 import Template
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
        tb_dict = self.parameters['testbed']._to_dict()
        self.variables = tb_dict.get('custom', {}).get('variables', {})
        self.data = {}
        self.action_runner = ActionRunner()
    
    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, param_data):
        if not param_data:
            self._data = {}
        else:
            self.variables.update(self.parameters.get('variables', {}))
            data_str = yaml.dump(
                param_data,
                Dumper=yamlordereddictloader.Dumper
            )
            data_str = self._substitute_variables(data_str)
            self._data = yaml.load(
                data_str,
                Loader=yamlordereddictloader.Loader
            )

    def _substitute_variables(self, data_str):
        """Replace variables with valid values."""
        try:
            # default is {{ myvaraible }}
            tpl = Template(data_str)
            data_str = tpl.render(self.variables)
            # for xpath, variable is _- myvariable -_
            tpl2 = Template(data_str,
                            variable_start_string="_-",
                            variable_end_string="-_")
            data_str = tpl2.render(self.variables)
        except TypeError:
            pass
        return data_str

    def _step_test(self, step, testbed):
        if not self.data:
            self.data = self.parameters.get('data', {})
        actions = self.parameters.get('test_actions', {})

        for action in actions:
            name = 'RUN ' + action.get('action', 'unknown')
            with step.start(name.upper()) as test_step:
                self.action_runner.run_banner(action)
                self.action_runner.run_log(action)
                if not self.action_runner.run(action, self.data, testbed):
                    test_step.failed()

    @aetest.test
    def run_pipeline_test(self, testbed, steps, suites={}):
        """Run test actions defined in Model Pipeline tests."""
        # argparse here to catch sys.argv
        self._step_test(steps, testbed)


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
            self.log.debug(banner(action['banner']))

    def run_log(self, action):
        if 'log' in action:
            self.log.debug(action['log'])
