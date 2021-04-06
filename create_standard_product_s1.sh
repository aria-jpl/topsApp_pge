#!/bin/bash
export TOPSAPP="/home/ops/topsApp_pge"
source /opt/isce2/isce_env.sh
export PYTHONPATH="$ISCE_HOME/applications:$ISCE_HOME/components:$TOPSAPP:$PYTHONPATH"
# This slows down c5.9xLarge instances too much
# export OMP_NUM_THREADS=16

# source environment
source $HOME/verdi/bin/activate

echo "##########################################" 1>&2
echo -n "Running S1 Standard Coseismic Product interferogram generation : " 1>&2
date 1>&2
python $TOPSAPP/create_standard_product_s1.py > standard_product_s1.log 2>&1
STATUS=$?
echo -n "Finished running S1 Standard Coseismic Propduct interferogram generation: " 1>&2
date 1>&2
if [ $STATUS -ne 0 ]; then
  echo "Failed to run S1 Standard Coseismic Product interferogram generation." 1>&2
  # echo "# ----- errors|exception found in log -----" >> _alt_traceback.txt && grep -i "error\|exception" standard_product_s1.log >> _alt_traceback.txt
  cat standard_product_s1.log 1>&2
  echo "{}"
  exit $STATUS
fi
