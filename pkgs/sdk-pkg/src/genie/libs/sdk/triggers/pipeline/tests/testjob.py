import os
from genie.harness.main import gRun

test_list = [
    'BGPglobalTest',
    'BGPneighborTest'
]

def main():
    test_path = os.path.dirname(os.path.abspath(__file__))

    gRun(trigger_uids=test_list,
         trigger_datafile='testspec_example.yaml',
         subsection_datafile='subsection_datafile.yaml')

