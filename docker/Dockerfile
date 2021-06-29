FROM hysds/isce2:latest-es1

LABEL description="TopsApp PGE Container"

# copy ariamh code ensure proper permissions, and move dependencies to final locations
COPY . /home/ops/topsApp_pge

RUN set -ex \
    && sudo /opt/conda/bin/conda install -c conda-forge --yes httplib2 lxml pyproj joblib pandas geopandas rasterio tmux jupyter \
    && sudo /home/ops/verdi/bin/pip install --upgrade pyproj \
    && $HOME/verdi/bin/pip install --upgrade elasticsearch-dsl elasticsearch boto3 \
    && /opt/conda/bin/pip install --upgrade elasticsearch-dsl elasticsearch \
    && /opt/conda/bin/pip install git+https://github.com/aria-jpl/dem_stitcher.git \
    && $HOME/verdi/bin/pip install 'fiona==1.7.13' \
    && sudo rm -rf /root/.cache \
    && sudo chown -R ops:ops /home/ops/topsApp_pge \
    && sudo cp -u /home/ops/topsApp_pge/shadow_mask/runTopo.py /opt/isce2/isce/components/isceobj/TopsProc/ \
    && sudo cp -u /home/ops/topsApp_pge/shadow_mask/runMergeBursts.py /opt/isce2/isce/components/isceobj/TopsProc/

# set entrypoint
WORKDIR /home/ops
CMD ["/bin/bash", "--login"]
