Setting Develoment Environment
==============================

# Install latest python
python -m venv venv
# Upgrade to latest pip
source venv/bin/activate
pip install --upgrade pip
# Install latest internal version of genie so that you get source code not compiled in .so file (easier to debug)
pip install genie --index-url http://pyats-pypi.cisco.com/simple --trusted-host pyats-pypi.cisco.com
# Clone genielibs (contains triggers)
git clone ssh://git@bitbucket-eng-sjc1.cisco.com:7999/pyats-pypi/genielibs.git
# Setup development environment
cd genielibs
make develop
# Model pipeline TestSpec in in genielibs/src/sdk/triggers/pipeline/
# Test example is in genielibs/src/sdk/triggers/pipeline/tests/
# Run example:
pyats run job testspec_example.yaml -t testbed_example.yaml --pdb --no-mail



git clone ssh://git@bitbucket-eng-sjc1.cisco.com:7999/pyats-pypi/genieparser.git
  680  cd genieparser/
  681  ls
  682  make develop