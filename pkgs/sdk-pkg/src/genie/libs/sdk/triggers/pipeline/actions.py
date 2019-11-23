import os
import time
from datetime import datetime
from .yangexec import run_netconf
from .cliverify import CliVerify


def run_cli(cls, action, data, testbed):
    cliv = CliVerify(action, testbed, data, cls.log)
    return cliv.run_cli()

def run_yang(cls, action, data, testbed):
    protocol = action.get('protocol')
    if protocol == 'netconf':
        return run_netconf(action, data, testbed, cls.log)
    return True


def run_sleep(cls, action, data, testbed):
    time.sleep(action.get('time', 0))
    return True


def run_repeat(cls, action, data, testbed):
    cls.log.info('{0}'.format(action))
    return True


def run_empty(cls, action={}, data={}, testbed={}):
    cls.log.error('NOT IMPLEMENTED: {0}\n{1}'.format(
            action.get('action', 'missing'),
            action
        )
    )
    return True


def run_timestamp(cls, action, data, testbed):
    graph = action.get('storage', '')
    precision = action.get('precision', 0)
    category = action.get('category', '')
    n = datetime.now()
    cls.log.debug('TIMESTAMP: DATE: {0} TIME: {1}'.format(
        n.strftime("%Y-%m-%d"),
        n.strftime("%H:%M:%S.%f")
    ))
    return True


actiondict = {
    'cli': run_cli,
    'yang': run_yang,
    'sleep': run_sleep,
    'repeat': run_repeat,
    'timestamp': run_timestamp,
    'empty': run_empty
}


class ActionMeta(type):

    @classmethod
    def __prepare__(metacls, name, bases):
        return actiondict

    def __new__(cls, name, bases, actiondict):
        return type.__new__(cls, name, bases, actiondict)
