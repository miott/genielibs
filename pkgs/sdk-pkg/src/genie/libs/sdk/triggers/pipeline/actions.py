import logging

log = logging.getLogger(__name__)


def run_cli(cls, action, data, testbed):
    print('RUN CLI\n{0}'.format(action))


def run_yang(cls, action, data, testbed):
    print('RUN YANG\n{0}'.format(action))


def run_sleep(cls, action, data, testbed):
    print('RUN SLEEP\n{0}'.format(action))


def run_repeat(cls, action, data, testbed):
    print('RUN REPEAT\n{0}'.format(action))


def run_empty(cls, action={}, data={}, testbed={}):
    print('NOT IMPLEMENTED: {0}\n{1}'.format(
            action.get('action', 'missing'),
            action
        )
    )


actiondict = {
    'cli': run_cli,
    'yang': run_yang,
    'sleep': run_sleep,
    'repeat': run_repeat,
    'empty': run_empty
}


class ActionMeta(type):

    @classmethod
    def __prepare__(metacls, name, bases):
        return actiondict

    def __new__(cls, name, bases, actiondict):
        return type.__new__(cls, name, bases, actiondict)