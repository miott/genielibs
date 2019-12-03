import logging
import re
from deepdiff import DeepDiff
from ats.log.utils import banner
from .utility import DataRetriever


class CliVerify:
    """Using a config from generated replays, produce CLI verification."""

    def __init__(self, action, testbed, data, logger):
        self.connection = action.get('action')
        self.uut = testbed.devices[action.get('device', 'uut')]
        self.log = logger
        # check if connected
        if not hasattr(self.uut, 'cli'):
            self.uut.connect(alias='cli', via=self.connection)
        elif hasattr(self.uut, 'cli') and not self.uut.cli.connected:
            self.uut.cli.connect()
        self.cmd, self.returns = DataRetriever.get_data(action, data)
        self.operation = action.get('operation')
        self.cc = CiscoConfig()

    def run_cli(self):
        """Execute CLI commands."""
        if not self.cmd:
            return

        resp = 'NO RESPONSE'
        result = True

        try:
            self.log.debug('CLI SEND:\n{0}'.format(self.cmd))
            resp = getattr(self.uut.cli, self.operation)(self.cmd)
            # TODO diff it? do a before after? just look for return?
        except Exception as e:
            self.log.error("CLI command failed:\n{0}\nERROR:\n{1}".format(
                self.cmd, e
            ))
            raise e

        if self.returns:
            added, removed = self.cc.diffs(
                self.cc.normalize(self.returns),
                self.cc.normalize(resp)
            )
            if added:
                self.log.error('Extra CLI:\n{0}'.format(added))
                self.log.error(banner('CLI VERIFICATION FAILED'))
                result = False
            if removed:
                self.log.error('Missing CLI:\n{0}'.format(removed))
                self.log.error(banner('CLI VERIFICATION FAILED'))
                result = False
        if result:
            self.log.debug(banner('CLI VERIFICATION SUCCEDED'))
        return result

    def before_rpc(self, cmd, counter, xpath, kind=''):
        """Collect CLI config before RPC is run

        - Create test is run first so needs a fresh pre-config.
        - Merge test is run second and has same pre-config as create.
        - Replace test is run third and has same pre-config as create.
        - Delete test is run fourth and needs a fresh pre-config because
          base config was changed by replace.
        - Remove test is run last and will use same pre-config as delete.

        Args:
          cmd (str): Show command.
          counter (str): Common for all tests of a single suite
          xpath (str): Common for all tests of a single suite.
          kind (str): Contains "basic " plus create, merge, replace, delete,
                      or remove.
        """
        index = counter + xpath
        replay_type = kind[kind.find('basic ') + 6:]

        if not cmd:
            cmd = 'show running'

        if replay_type in ['create', 'delete']:
            # These replays need a fresh pre-config to base diffs on
            resp = self.run_ssh(cmd, op='exec')
            self.common_cli_base[index] = self.cc.normalize(resp)
        elif replay_type in ['merge', 'remove', 'replace']:
            # Pre-config bases are same as create and delete pre-configs
            if index not in self.common_cli_base:
                resp = self.run_ssh(cmd, op='exec')
                self.common_cli_base[index] = self.cc.normalize(resp)

    def after_rpc(self, cmd, counter, xpath, kind):
        """Collect CLI config after RPC is run

        - Create test is run first and needs a fresh post-config.
        - Merge test is run second and uses same diff as create.
        - Replace test is run third, uses same pre-config as create,
          and needs a fresh post-config.
        - Delete test is run fourth, uses same pre-config as create,
          and needs a fresh post-config.
        - Remove is run last, uses the same diff as delete.

        Args:
          cmd (str): Show command.
          counter (str): Common for all tests of a single suite
          xpath (str): Common for all tests of a single suite.
          kind (str): Contains "basic " plus create, merge, replace, delete,
                      or remove.
        Returns:
          (list): Expected CLI after RPC is run.
        """
        expect = []
        index = counter + xpath
        replay_type = kind[kind.find('basic ') + 6:]

        if not cmd:
            cmd = 'show running'

        if replay_type in ['create', 'replace', 'delete']:
            cfg_pre = self.common_cli_base.get(index, [])
            resp = self.run_ssh(cmd, op='exec')
            cfg_post = self.cc.normalize(resp)
            added, removed = self.cc.diffs(cfg_pre, cfg_post)

            self.log.debug('{0}\nadded: {1}\nremoved: {2}\n'.format(
                ' - '.join([counter, xpath, replay_type]),
                added,
                removed)
            )
            expect = added + removed
            self.common_cli_diff[index] = expect
        elif replay_type in ['merge', 'remove']:
            expect = self.common_cli_diff.get(index, [])

        return ''.join(expect)

    def close(self):
        """Shut down open session."""
        if self.uut.cli.connected:
            self.uut.cli.disconnect()


class CiscoConfig:
    """CiscoConfig processes CLI commands to detect differences.

    Normalize CLI of 2 examples and determine differences.
    """

    skip = ["enable", "config", "t", "configure", "end", "show",
            "terminal", "commit", "#", "!", "<rpc", "Building"]

    timestamps = ["mon", "tue", "wed", "thu", "fri", "sat", "sun", "jan",
                  "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                  "oct", "nov", "dec"]

    timeregex = re.compile(
        "^(([0-1]?[0-9])|([2][0-3])):([0-5]?[0-9])(:([0-5]?[0-9]))?"
    )

    def _handle_intf(self, intf):
        # might be "interface GigabitEthernet 1/0/1"
        # or "interface GigabitEthernet1/0/1"
        intf_list = intf.split()
        intf_list.remove('interface')
        return "interface " + ''.join(intf_list)

    def _handle_username(self, username):
        # might be "username lab password 0 mypassword"
        # or "username lab password mypassword"
        return username.replace("password 0", "password", 1)

    def _handle_exit(self, line):
        # clear out "exit" if found
        if len(line.split()) == 1:
            return None
        return line

    special_handles = {"interface": _handle_intf,
                       "username": _handle_username,
                       "exit": _handle_exit}

    def _check_special_handles(self, line):

        if line.split()[0] in self.special_handles.keys():
            line = self.special_handles[line.split()[0]](self, line)
        return line

    def _check_timestamps(self, line):
        if line[:3].lower() in self.timestamps:
            for item in line.split():
                if self.timeregex.match(item):
                    return True
        return False

    def normalize(self, cfg):
        """Removes uninteresting CLI and returns structured data.

        Remove comments, organize blocks of config data,
        skip maintainence operations, and other tasks.

        NOTE: Copying and pasting a show running-config may have
        compare errors only specific to the show command so it is
        best to copy the config from device to file and use that text.

        Args:
          cfg (str): CLI text from a configuration copied off a Cisco device.
        Returns:
          listt: Configuration lines of interest.
        """
        clean_cfg = []

        for line in cfg.splitlines():

            if not line.strip():
                # empty line
                continue
            if "--More--" in line:
                # pick up anything that may be included after the "More"
                line = line[line.find('--More--') + 8:]
                if not line.split():
                    # emptied line
                    continue
            if line.startswith('#'):
                continue
            if line.startswith('!'):
                continue
            if line.startswith('Current configuration'):
                continue
            if line.rstrip().endswith("#"):
                continue
            if line.split()[0] in self.skip:
                continue
            if self._check_timestamps(line):
                continue
            line = self._check_special_handles(line)
            if line is None:
                continue

            clean_cfg.append(line.strip())

        return clean_cfg

    def diffs(self, cli_base, cli_after):
        """Identify the difference between 2 lists of normalized CLI text.

        Args:
          cli_base (list): CLI lines before added configuration.
          cli_after (list): CLI lines after added configuration.
        Returns:
          str: Lines of configuration that has changed
        """
        added_cli = []
        removed_cli = []

        ddiff = DeepDiff(cli_base, cli_after,
                         ignore_order=True,
                         report_repetition=True,
                         view='tree')
        added = ddiff.get('iterable_item_added', [])
        removed = ddiff.get('iterable_item_removed', [])
        repetition = ddiff.get('repetition_change', [])

        for add in added:
            added_cli.append(add.t2 + '\n')

        for remove in removed:
            removed_cli.append('-' + remove.t1 + '\n')

        for rep in repetition:
            # Include line before repeated CLI
            new_indexes = rep.repetition.get('new_indexes', [])
            old_indexes = rep.repetition.get('old_indexes', [])
            if rep.repetition.get(
                'old_repeat', 0) < rep.repetition.get(
                    'new_repeat', 0):
                for new_index in new_indexes:
                    line = rep.up.t2_child_rel.parent[new_index - 1]
                    for old_index in old_indexes:
                        if line == rep.up.t1_child_rel.parent[old_index - 1]:
                            break
                    else:
                        added_cli.append(line + '\n' + rep.t2 + '\n')
            else:
                for old_index in old_indexes:
                    line = rep.up.t1_child_rel.parent[old_index - 1]
                    for new_index in new_indexes:
                        if line == rep.up.t2_child_rel.parent[new_index - 1]:
                            break
                    else:
                        removed_cli.append(line + '\n-' + rep.t1 + '\n')

        return (added_cli, removed_cli)
