export TOPSAPP="/home/ops/topsApp_pge"
# chmod og-rw $TOPSAPP/.netrc
yes | cp -rf $TOPSAPP/.netrc $HOME/.netrc
export PYTHONPATH="$TOPSAPP:$PYTHONPATH"

sudo chown -R $USER:$USER /opt/conda
conda install -c conda-forge jupyter tmux --yes

source /opt/isce2/isce_env.sh
export PYTHONPATH="$ISCE_HOME/applications:$ISCE_HOME/components:$BASE_PATH:$ARIAMH_HOME:$PYTHONPATH"

# Make sure you run this in topsApp_pge
# sudo chown -R $(id -u):$(id -g) $PWD
# Allow all Read and write access
cd $TOPSAPP
chmod -R 0777 $PWD