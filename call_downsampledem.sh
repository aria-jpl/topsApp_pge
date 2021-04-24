#!/bin/bash
export TOPSAPP="/home/ops/topsApp_pge"
source /opt/isce2/isce_env.sh
export PYTHONPATH="$ISCE_HOME/applications:$ISCE_HOME/components:$TOPSAPP:$PYTHONPATH"
export OMP_NUM_THREADS=16
export PROJ_LIB="/opt/conda/share/proj"

# source environment
source $HOME/verdi/bin/activate

# example: /opt/isce2/isce/applications/downsampleDEM.py -i SRTM_preprocess_dem/demLat_N37_N42_Lon_E091_E096.dem.wgs84.vrt -rsec 3
$ISCE_HOME/applications/downsampleDEM.py -i $1 -rsec 3
echo "return status: $?"
