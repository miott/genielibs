#! /usr/bin/env python
import sys
from pprint import pprint as pp
import json
from collections import OrderedDict
import yaml
import yamlordereddictloader


def load(filename):
    #
    # Load test YAML file as OrderedDict:
    #
    test = yaml.load(
        open(filename),
        Loader=yamlordereddictloader.Loader
    )

    print('\n\nYAML to DICT\n\n')
    pp(test)
    #
    # Dump test to a JSON file:
    #
    with open(filename.replace('.yaml', '.json'), 'w') as fd:
        json.dump(test, fd, indent=2)
    #
    # Load test JSON file as OrderedDict:
    #
    with open(filename.replace('.yaml', '.json')) as fd:
        test = json.load(fd, object_pairs_hook=OrderedDict)
    print('\n\nJSON to DICT\n\n')
    pp(test)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = 'test-schema-example.yaml'

    load(filename)
