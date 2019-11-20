import os

from genie.harness.main import gRun


def main():
    test_path = os.path.dirname(os.path.abspath(__file__))

    gRun(trigger_uids=['BGPglobalTest', 'BGPneighborTest'],
         trigger_datafile='testspec_example.yaml',
         subsection_datafile='subsection_datafile.yaml')

