export TOPSAPP="/home/ops/topsApp_pge"
export PYTHONPATH="$TOPSAPP:$PYTHONPATH"

# This is very slow
# sudo chown -R $USER:$USER /opt/conda
# conda install -c conda-forge jupyter tmux --yes
pip install jupyter

source /opt/isce2/isce_env.sh
export PYTHONPATH="$ISCE_HOME/applications:$ISCE_HOME/components:$BASE_PATH:$ARIAMH_HOME:$PYTHONPATH"

# If you have permission issues,
# you may run this in topsApp_pge:
#
# Remote server
# sudo chown -R $(id -u):$(id -g) $PWD
# OR
#
# local machine
# Allow all Read and write access
# cd $TOPSAPP
# chmod -R 0777 $PWD