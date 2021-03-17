#!/usr/bin/env python3
from __future__ import division
from builtins import str
from builtins import range
from past.utils import old_div
import os
import sys
import re
import requests
import json
import shutil
import traceback
import logging
import hashlib
import math
from subprocess import (check_call,
                        CalledProcessError)
from glob import glob
from lxml.etree import parse
import numpy as np
from datetime import datetime
from osgeo import (ogr,
                   gdal)
from isceobj.Image.Image import Image
from topsApp_utils.UrlUtils import UrlUtils
from topsApp_utils.imutils import (get_image,
                                   get_size,
                                   crop_mask)
from topsApp_utils.fetchCalES import fetch as fetch_aux_cal

from topsApp_utils.sent1_bbox import get_envelope_from_all_slcs
from topsApp_utils.time_utils import getTemporalSpanInDays
from dateutil import parser
from string import Template
from iscesys.Component.ProductManager import ProductManager as PM
from pathlib import Path
import zipfile
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search, Q

gdal.UseExceptions()  # make GDAL raise python exceptions


BASE_PATH = os.path.dirname(__file__)

RESORB_RE = re.compile(r'_RESORB_')
MISSION_RE = re.compile(r'^(S1\w)_')
POL_RE = re.compile(r'^S1\w_IW_SLC._1S(\w{2})_')

#  Read conf/settings.conf
SETTINGS_DICT = UrlUtils()
if 'ES_USERNAME' in SETTINGS_DICT:
    ES_USERNAME = SETTINGS_DICT['ES_USERNAME']
    ES_PASSWORD = SETTINGS_DICT['ES_PASSWORD']
    HTTP_AUTH = (ES_USERNAME, ES_PASSWORD)
else:
    HTTP_AUTH = None

dem_user = SETTINGS_DICT['ARIA_DEM_U']
dem_pass = SETTINGS_DICT['ARIA_DEM_P']

# topsApp Path in container
TOPS_APP_PATH = os.environ['TOPSAPP']

# Read Context File
with open('_context.json') as file:
    ctx = json.load(file)

# The job_spec_id should match the `job-{string trailing job-spec json}`
JOB_SPEC_ID, branch = ctx['job_specification']['id'].split(':')
# Hysds append `job-` to id
JOB_SPEC_ID = JOB_SPEC_ID.replace('job-', '')

ACCEPTED_JOB_TYPES = ['coseismic-s1gunw-topsapp',
                      'standard-product-s1gunw-topsapp']

# This will never happen because of job-spec and hysds-io setup.
# Still it is instructive within PGE to illustrate we have two pipeliens
if JOB_SPEC_ID not in ACCEPTED_JOB_TYPES:
    job_types_str = ', '.join(ACCEPTED_JOB_TYPES)
    raise ValueError(f'Job type {JOB_SPEC_ID} not understood; '
                     f'must be {job_types_str}')

# Open config file replacing `job-` with `config-` at the beginning
config_file_path = f'{TOPS_APP_PATH}/conf/config-{JOB_SPEC_ID}.json'
with open(config_file_path) as file:
    config_data = json.load(file)

# Coseismic vs. Standard Product Global Variables
DATASET_KEY = config_data['dataset_key']
ES_INDEX = f'grq_*_{DATASET_KEY.lower()}'

# will be `coseismic` or `standard-product`
JOB_NAME = config_data['name']

# Fill in using config
IFG_ID_SP_TMPL = f'{DATASET_KEY}' + '-{}-{}-{:03d}-tops-{}_{}-{}-{}-PP-{}-{}'

# Log name
# Note this actually reads the standard out so if you change the above
# Make sure to change the `create_standard_product.sh`, too!
LOG_NAME = 'standard_product_s1.log'

log_format = '[%(asctime)s: %(levelname)s/%(funcName)s] %(message)s'
logging.basicConfig(filename=LOG_NAME,
                    format=log_format,
                    level=logging.INFO)
logger = logging.getLogger('create_ifg')
logger.info(f'The job type is {JOB_NAME}')

# Check if Coseismic Job Name Matches IFG-CFG
input_metadata = ctx['input_metadata']
MACHINE_TAGS = input_metadata.get('tags', [])


# Use the same template file and then adapt based on context.json
TEMPLATE_FILE = (os.environ['TOPSAPP'] +
                 '/topsApp_standard_product.xml.tmpl')


def update_met_key(met_md, old_key, new_key):
    try:
        if old_key in met_md:
            met_md[new_key] = met_md.pop(old_key)
    except Exception as err:
        out = (f'Failed to replace {old_key} from met file with {new_key}'
               f'Error : {str(err)}')
        print(out)
    return met_md


def delete_met_data(met_md, old_key):
    try:
        if old_key in met_md:
            del met_md[old_key]
    except Exception as err:
        print(f'Failed to delete {old_key} from met file. Error : {str(err)}')

    return met_md


def touch(path):
    with open(path, 'a'):
        os.utime(path, None)


def fileContainsMsg(file_name, msg):
    with open(file_name, 'r') as f:
        datafile = f.readlines()
    for line in datafile:
        if msg in line:
            # found = True # Not necessary
            return True, line
    return False, None


def checkBurstError():
    msg = 'cannot continue for interferometry applications'

    found, line = fileContainsMsg(LOG_NAME, msg)
    if found:
        logger.info(f'checkBurstError : {line.strip()}')
        raise RuntimeError(line.strip())
    if not found:
        msg = 'Exception: Could not determine a suitable burst offset'
        found, line = fileContainsMsg(LOG_NAME, msg)
        if found:
            logger.info(f'Found Error : {line}')
            raise RuntimeError(line.strip())


def get_md5_from_file(file_name):
    """
    :param file_name: file path to the local SLC file after download
    :return: string, ex. 8e15beebbbb3de0a7dbed50a39b6e41b ALL LOWER CASE
    """
    hash_md5 = hashlib.md5()
    with open(file_name, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def check_ifg_status_by_hash_version(new_ifg_hash, version):
    es_url = SETTINGS_DICT['GRQ_URL']

    grq_client = Elasticsearch(es_url,
                               http_auth=HTTP_AUTH,
                               verify_certs=False,
                               )

    s = Search(using=grq_client, index=ES_INDEX)

    q = Q('bool', must=[Q('term',
                          **{'metadata.full_id_hash.raw': new_ifg_hash}),
                        Q('term',
                          **{'version.raw': version})
                        ])
    s = s.query(q)
    logger.info('query made to ES is:')
    logger.info(json.dumps(s.to_dict(), indent=2))
    total = s.count()

    logger.info('check_slc_status_by_hash : total : %s' % total)
    if total > 0:
        logger.info('Duplicate dataset for hash_id: %s' % new_ifg_hash)
        sys.exit(0)

    logger.info('check_slc_status : returning False')
    return False


def update_met(md):

    # Keys to update
    md = update_met_key(md, 'sensingStart', 'sensing_start')
    md = update_met_key(md, 'trackNumber', 'track_number')
    md = update_met_key(md, 'imageCorners', 'image_corners')
    md = update_met_key(md, 'lookDirection', 'look_direction')
    md = update_met_key(md, 'inputFile', 'input_file')
    md = update_met_key(md, 'startingRange', 'starting_range')
    md = update_met_key(md, 'latitudeIndexMax', 'latitude_index_max')
    md = update_met_key(md, 'frameID', 'frame_id')
    md = update_met_key(md, 'frameNumber', 'frame_number')
    md = update_met_key(md, 'beamID', 'beam_id')
    md = update_met_key(md, 'orbitNumber', 'orbit_number')
    md = update_met_key(md, 'latitudeIndexMin', 'latitude_index_min')
    md = update_met_key(md, 'beamMode', 'beam_mode')
    md = update_met_key(md, 'orbitRepeat', 'orbit_repeat')
    md = update_met_key(md, 'perpendicularBaseline', 'perpendicular_baseline')
    md = update_met_key(md, 'frameName', 'frame_name')
    md = update_met_key(md, 'sensingStop', 'sensing_stop')
    md = update_met_key(md, 'parallelBaseline', 'parallel_baseline')
    md = update_met_key(md, 'direction', 'orbit_direction')

    # keys to delete
    md = delete_met_data(md, 'swath')
    md = delete_met_data(md, 'spacecraftName')
    md = delete_met_data(md, 'reference')

    return md


def get_ifg_hash(master_slcs,  slave_slcs):

    master_ids_str = ''
    slave_ids_str = ''

    for slc in sorted(master_slcs):
        print('get_ifg_hash : master slc : %s' % slc)
        if isinstance(slc, tuple) or isinstance(slc, list):
            slc = slc[0]

        if master_ids_str == '':
            master_ids_str = slc
        else:
            master_ids_str += ' ' + slc

    for slc in sorted(slave_slcs):
        print('get_ifg_hash: slave slc : %s' % slc)
        if isinstance(slc, tuple) or isinstance(slc, list):
            slc = slc[0]

        if slave_ids_str == '':
            slave_ids_str = slc
        else:
            slave_ids_str += ' '+slc

    id_hash = hashlib.md5(json.dumps([
            master_ids_str,
            slave_ids_str
            ]).encode('utf8')).hexdigest()
    return id_hash


def get_date(t):
    try:
        return datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%fZ')
    except Exception as err:
        logger.debug(f'{str(err)}')
        try:
            return datetime.strptime(t, '%Y-%m-%dT%H:%M:%S')
        except Exception as err:
            logger.debug(f'{str(err)}')
            return datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%f')


def get_center_time(t1, t2):
    a = get_date(t1)
    b = get_date(t2)
    t = a + old_div((b - a), 2)
    return t.strftime('%H%M%S')


def get_time(t):

    logger.info('get_time(t) : %s' % t)
    t = parser.parse(t).strftime('%Y-%m-%dT%H:%M:%S')
    t1 = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S')
    logger.info('returning : %s' % t1)
    return t1


def get_time_str(t):

    logger.info('get_time(t) : %s' % t)
    t = parser.parse(t).strftime('%Y-%m-%dT%H:%M:%S')
    return t


def get_date_str(t):

    logger.info('get_time(t) : %s' % t)
    t = parser.parse(t).strftime('%Y-%m-%d')
    return t


def convert_number(x):

    x = float(x)
    data = ''
    y = abs(x)
    pre_y = str(y).split('.')[0]
    if int(pre_y) > 99:
        pre_y = pre_y[:2]
    else:
        pre_y = pre_y.rjust(2, '0')

    post_y = '000'
    post_y = str(y).split('.')[1]

    if int(post_y) > 999:
        post_y = post_y[:3]
    else:
        print('post_y[0:3] : {}'.format(post_y[0:3]))
        if post_y[0:3] == '000':
            post_y = '000'
        else:
            post_y = post_y.ljust(3, '0')

    print('post_y : %s ' % post_y)

    if x < 0:
        data = '{}{}S'.format(pre_y, post_y)
    else:
        data = '{}{}N'.format(pre_y, post_y)

    return data


def get_minmax(geojson):
    """returns the minmax tuple of a geojson"""
    lats = [x[1] for x in geojson['coordinates'][0]]
    return min(lats), max(lats)


def get_geocoded_lats(vrt_file):
    """ return latitudes"""
    import gdal
    import numpy as np

    # extract geo-coded corner coordinates
    ds = gdal.Open(vrt_file)
    gt = ds.GetGeoTransform()
    rows = ds.RasterYSize

    lat_arr = list(range(0, rows))
    lats = np.empty((rows,), dtype='float64')
    for py in lat_arr:
        lats[py] = gt[3] + (py * gt[5])

    return lats


def get_updated_met(metjson):
    new_met = {}
    return new_met


def get_tops_subswath_xml(masterdir):
    """
    Find all available IW[1-3].xml files
    """

    logger.info('get_tops_subswath_xml from : %s' % masterdir)

    masterdir = os.path.abspath(masterdir)
    IWs = glob(os.path.join(masterdir, 'IW*.xml'))
    if len(IWs) < 1:
        raise Exception('Could not find a IW*.xml file in ' + masterdir)

    return IWs


def read_isce_product(xmlfile):
    logger.info('read_isce_product: %s' % xmlfile)

    # check if the file does exist
    check_file_exist(xmlfile)

    # loading the xml file with isce
    pm = PM()
    pm.configure()
    obj = pm.loadProduct(xmlfile)
    return obj


def check_file_exist(infile):
    logger.info('check_file_exist : %s' % infile)
    if not os.path.isfile(infile):
        raise Exception(infile + ' does not exist')
    else:
        logger.info('%s Exists' % infile)


def get_tops_metadata(masterdir):

    logger.info('get_tops_metadata from : %s' % masterdir)
    # get a list of avialble xml files for IW*.xml
    IWs = get_tops_subswath_xml(masterdir)
    # append all swaths togheter
    frames = []
    for IW in IWs:
        logger.info('get_tops_metadata processing : %s' % IW)
        obj = read_isce_product(IW)
        frames.append(obj)

    output = {}
    dt = min(frame.sensingStart for frame in frames)
    output['sensingStart'] = dt.isoformat('T') + 'Z'
    logger.info(dt)
    dt = max(frame.sensingStop for frame in frames)
    output['sensingStop'] = dt.isoformat('T') + 'Z'
    logger.info(dt)
    return output


def get_version():
    """Get dataset version."""
    tops_app_path = os.environ['TOPSAPP']
    DS_VERS_CFG = f'{tops_app_path}/conf/dataset_versions.json'
    with open(DS_VERS_CFG) as f:
        ds_vers = json.load(f)
    return ds_vers[DATASET_KEY]


def get_area(coords):
    """Get area of enclosed coordinates- determines clockwise
    or counterclockwise order"""
    n = len(coords)  # number of corners
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][1] * coords[j][0]
        area -= coords[j][1] * coords[i][0]
    return old_div(area, 2)


def create_dataset_json(id, version, met_file, ds_file):
    """Write dataset json."""
    # get metadata
    with open(met_file) as f:
        md = json.load(f)

    # build dataset
    ds = {
        'creation_timestamp': '%sZ' % datetime.utcnow().isoformat(),
        'version': version,
        'label': id
    }

    try:
        coordinates = md['union_geojson']['coordinates']

        cord_area = get_area(coordinates[0])
        if not cord_area > 0:
            logger.info('creating dataset json. '
                        'Coordinates are not clockwise, reversing them.')
            coordinates = [coordinates[0][::-1]]
            logger.info(coordinates)
            cord_area = get_area(coordinates[0])
            if not cord_area > 0:
                logger.info('creating dataset json. '
                            'Coordinates are STILL NOT clockwise')
        else:
            logger.info('Creating dataset json. '
                        'Coordinates are already clockwise')

        ds['location'] = {'type': 'Polygon', 'coordinates': coordinates}
        logger.info('create_dataset_json location : %s' % ds['location'])

    except Exception as err:
        logger.info('create_dataset_json: Exception : ')
        logger.warn(str(err))
        logger.warn('Traceback: {}'.format(traceback.format_exc()))

    # set earliest sensing start to starttime
    # and latest sensing stop to endtime
    if isinstance(md['sensing_start'], str):
        ds['starttime'] = md['sensing_start']
    else:
        md['sensing_start'].sort()
        ds['starttime'] = md['sensing_start'][0]

    if isinstance(md['sensing_stop'], str):
        ds['endtime'] = md['sensing_stop']
    else:
        md['sensing_stop'].sort()
        ds['endtime'] = md['sensing_stop'][-1]

    # write out dataset json
    with open(ds_file, 'w') as f:
        json.dump(ds, f, indent=2)


def get_union_polygon(ds_files):
    """Get GeoJSON polygon of union of IFGs."""

    geom_union = None
    for ds_file in ds_files:
        with open(ds_file) as f:
            ds = json.load(f)
        geom = ogr.CreateGeometryFromJson(json.dumps(ds['location'],
                                          indent=2,
                                          sort_keys=True))
        if geom_union is None:
            geom_union = geom
        else:
            geom_union = geom_union.Union(geom)
    return json.loads(geom_union.ExportToJson()), geom_union.GetEnvelope()


def get_bool_param(ctx, param):
    """Return bool param from context."""

    if param in ctx and isinstance(ctx[param], bool):
        return ctx[param]
    return True if ctx.get(param, 'true').strip().lower() == 'true' else False


def download_file(url, outdir='.', session=None):
    """Download file to specified directory."""

    if session is None:
        session = requests.session()
    path = os.path.join(outdir, os.path.basename(url))
    logger.info('Downloading URL: {}'.format(url))
    r = session.get(url, stream=True, verify=False)
    try:
        success = True
    except Exception as e:
        logger.info(str(e))
        success = False
    if success:
        with open(path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()
    return success


def get_temp_id(ctx, version):
    ifg_hash = ctx['new_ifg_hash']
    direction = ctx['direction']
    slave_ifg_dt = ctx['slc_slave_dt']
    master_ifg_dt = ctx['slc_master_dt']
    track = ctx["track_number"]

    sat_direction = 'D'

    if direction.lower() == 'asc':
        sat_direction = 'A'

    ifg_hash = ifg_hash[0:4]
    ifg_id = IFG_ID_SP_TMPL.format(sat_direction,
                                   'R',
                                   track,
                                   master_ifg_dt.split('T')[0],
                                   slave_ifg_dt.split('T')[0],
                                   '*',
                                   '*',
                                   ifg_hash,
                                   version.replace('.', '_'))

    return ifg_id


def get_polarization2(id):
    """Return polarization.
    SH (single HH polarisation)
    SV (single VV polarisation)
    DH (dual HH+HV polarisation)
    DV (dual VV+VH polarisation)
    """

    match = POL_RE.search(id)
    if not match:
        raise RuntimeError('Failed to extract polarization from %s' % id)
    pp = match.group(1)
    if pp == 'DV':
        return 'vv'
    elif pp == 'SV':
        return 'vv'
    elif pp == 'DH':
        return 'hh'
    elif pp == 'SH':
        return 'hh'
    else:
        raise RuntimeError('Unrecognized polarization: %s' % pp)


def get_pol_data_from_slcs(slcs):
    pol_data = []
    for slc in slcs:
        pol = get_polarization(slc).strip().lower()
        logger.info('get_pol_data_from_slcs:'
                    f'pol data of SLC : {slc} is {pol}')
        if pol not in pol_data:
            pol_data.append(pol)

    if (len(pol_data) == 0) or (len(pol_data) > 1):
        err_msg = ('get_pol_data_from_slcs: Found Multiple Polarization '
                   f'or No Polarization for slcs {slcs} : {pol_data}')
        print(err_msg)
        raise RuntimeError(err_msg)

    return pol_data[0]


def get_polarization(id):
    """Return polarization."""

    match = POL_RE.search(id)
    if not match:
        raise RuntimeError('Failed to extract polarization from %s' % id)
    pp = match.group(1)
    if pp in ('SV', 'DV'):
        return 'vv'
    elif pp in ('DH', 'SH'):
        return 'hh'
    else:
        raise RuntimeError('Unrecognized polarization: %s' % pp)


def file_transform(infile, maskfile, maskfile_out):
    """
        convert file into the same geo frame as the input file
        both files to be gdal compatible and with geo-coordinates
    """

    from osgeo import gdal, gdalconst

    # convert all to absolute paths
    maskfile = os.path.abspath(maskfile)
    maskfile_out = os.path.abspath(maskfile_out)

    # Source
    src = gdal.Open(maskfile, gdalconst.GA_ReadOnly)
    src_proj = src.GetProjection()
    print('Working on ' + maskfile)

    # We want a section of source that matches this:
    match_ds = gdal.Open(infile, gdalconst.GA_ReadOnly)
    match_proj = match_ds.GetProjection()
    match_geotrans = match_ds.GetGeoTransform()
    print('Getting target reference information')
    wide = match_ds.RasterXSize
    high = match_ds.RasterYSize

    # Output / destination
    dst = gdal.GetDriverByName('envi').Create(maskfile_out,
                                              wide,
                                              high, 1,
                                              gdalconst.GDT_Float32)
    dst.SetGeoTransform(match_geotrans)
    dst.SetProjection(match_proj)

    # Do the work
    gdal.ReprojectImage(src,
                        dst,
                        src_proj,
                        match_proj,
                        gdalconst.GRA_NearestNeighbour)
    print('Done')
    print('')

    # closing the images
    dst = None
    src = None


def move_dem_separate_dir(dir_name):
    move_dem_separate_dir_SRTM(dir_name)
    move_dem_separate_dir_NED(dir_name)


def move_dem_separate_dir_SRTM(dir_name):
    logger.info('move_dem_separate_dir_SRTM : %s' % dir_name)
    create_dir(dir_name)

    move_cmd = ['mv', 'demLat*', dir_name]
    move_cmd_line = ' '.join(move_cmd)
    logger.info('Calling {}'.format(move_cmd_line))
    call_noerr(move_cmd_line)


def move_dem_separate_dir_NED(dir_name):
    logger.info('move_dem_separate_dir_NED : %s' % dir_name)
    create_dir(dir_name)
    move_cmd = ['mv', 'stitched.*', dir_name]
    move_cmd_line = ' '.join(move_cmd)
    logger.info('Calling {}'.format(move_cmd_line))
    call_noerr(move_cmd_line)

    move_cmd = ['mv', '*DEM.vrt', dir_name]
    move_cmd_line = ' '.join(move_cmd)
    logger.info('Calling {}'.format(move_cmd_line))
    call_noerr(move_cmd_line)


def create_dir(dir_name):
    if not os.path.isdir(dir_name):
        mkdir_cmd = ['mkdir', dir_name]
        mkdir_cmd_line = ' '.join(mkdir_cmd)
        logger.info('create_dir : Calling {}'.format(mkdir_cmd_line))
        call_noerr(mkdir_cmd_line)


def call_noerr(cmd):
    """Run command and warn if exit status is not 0."""

    try:
        check_call(cmd, shell=True)
    except Exception as e:
        logger.warn('Got exception running {}: {}'.format(cmd, str(e)))
        logger.warn('Traceback: {}'.format(traceback.format_exc()))


def unzip_annotation_xmls(zip_path: str) -> list:
    zip_obj = zipfile.ZipFile(zip_path, 'r')
    all_files = zip_obj.filelist
    # Only want xmls that match this regular expression
    # (within annotation file)
    pattern = re.compile(r'S1\w*.SAFE/annotation/s1[\w\-]*.xml')
    xmls = list(filter(lambda x: re.match(pattern, x.filename), all_files))

    def extract(zip_info_ob):
        zip_obj.extract(zip_info_ob)
        fn = zip_info_ob.filename
        logger.info(f'Unzipping {fn}')
        return fn

    out = list(map(extract, xmls))

    return out


def main():
    """HySDS PGE wrapper for TopsInSAR interferogram generation."""

    # save cwd (working directory)
    complete_start_time = datetime.now()
    logger.info('TopsApp End Time : {}'.format(complete_start_time))
    cwd = os.getcwd()

    # If there is a machine tag, check that it's coseismic
    # otherwise make sure it's
    # the standard product.
    # New machine tags other than "s1-coseismic-gunw"
    # will need new control flow.
    if MACHINE_TAGS:
        if not ((MACHINE_TAGS[0] == "s1-coseismic-gunw")
                and (JOB_NAME == 'coseismic')):
            exception_msg = ('TopsApp Pipelines were mixed: '
                             'A coseismic job was called with a '
                             'standard product ifg-cfg')
            raise RuntimeError(exception_msg)
    elif JOB_NAME != 'standard-product':
        exception_msg = ('TopsApp Pipelines were mixed: '
                         'A standard product job was called with a '
                         'coseismic ifg-cfg')
        raise RuntimeError(exception_msg)
    else:
        pass
    logger.info(f'The machine tag and job name agree for '
                f'the {JOB_NAME} pipeline')

    input_metadata = ctx['input_metadata']
    if type(input_metadata) is list:
        input_metadata = input_metadata[0]

    # get args
    project = input_metadata['project']
    if type(project) is list:
        project = project[0]

    ifg_cfg_id = input_metadata['id']
    master_ids = input_metadata['master_scenes']
    slave_ids = input_metadata['slave_scenes']
    direction = input_metadata['direction']
    platform = input_metadata['platform']
    master_zip_file = input_metadata['master_zip_file']
    slave_zip_file = input_metadata['slave_zip_file']
    master_orbit_file = input_metadata['master_orbit_file']
    slave_orbit_file = input_metadata['slave_orbit_file']
    master_orbit_url = input_metadata['master_orbit_url']
    slave_orbit_url = input_metadata['slave_orbit_url']
    track = input_metadata['track_number']
    dem_type = input_metadata['dem_type']
    system_version = ctx['container_image_name'].strip().split(':')[-1].strip()
    ctx['system_version'] = system_version
    full_id_hash = input_metadata['full_id_hash']
    ctx['full_id_hash'] = full_id_hash

    new_ifg_hash = get_ifg_hash(master_ids, slave_ids)
    ctx['new_ifg_hash'] = new_ifg_hash

    slc_slave_dt = input_metadata['slc_slave_dt']
    ctx['slc_slave_dt'] = slc_slave_dt
    slc_master_dt = input_metadata['slc_master_dt']
    ctx['slc_master_dt'] = slc_master_dt
    if dem_type == 'Ned1':
        dem_type = 'NED1'

    ctx['dem_type'] = dem_type
    ctx['ifg_cfg_id'] = ifg_cfg_id

    orbit_type = 'poeorb'
    for o in (master_orbit_url, slave_orbit_url):
        if RESORB_RE.search(o):
            orbit_type = 'resorb'
            break
    ctx['orbit_type'] = orbit_type

    for key in list(input_metadata.keys()):
        if key not in list(ctx.keys()):
            ctx[key] = input_metadata[key]
            logger.info(f'Added {key} key to ctx')
        else:
            logger.info(f'key {key} already in ctx with value {ctx[key]}'
                        f' and input_metadata value is {input_metadata[key]}')
    logger.info('ctx: {}'.format(json.dumps(ctx, indent=2)))

    azimuth_looks = 7
    if 'azimuth_looks' in input_metadata:
        azimuth_looks = int(input_metadata['azimuth_looks'])
    ctx['azimuth_looks'] = azimuth_looks

    range_looks = 19
    if 'range_looks' in input_metadata:
        range_looks = int(input_metadata['range_looks'])
    ctx['range_looks'] = range_looks

    filter_strength = 0.5
    if 'filter_strength' in input_metadata:
        filter_strength = float(input_metadata['filter_strength'])
    ctx['filter_strength'] = filter_strength

    precise_orbit_only = True
    if 'precise_orbit_only' in input_metadata:
        precise_orbit_only = get_bool_param(input_metadata,
                                            'precise_orbit_only')
    ctx['precise_orbit_only'] = precise_orbit_only

    ifg_hash = new_ifg_hash[0:4]
    ctx['ifg_hash'] = ifg_hash

    logger.info('ifg_hash : %s' % ifg_hash)

    # Pull topsApp configs
    ctx['azimuth_looks'] = ctx.get('context', {}).get('azimuth_looks', 7)
    ctx['range_looks'] = ctx.get('context', {}).get('range_looks', 19)

    ctx.setdefault('swathnum', [1, 2, 3])
    ctx['stitch_subswaths_xt'] = True
    azimuth_looks = ctx['azimuth_looks']
    range_looks = ctx['range_looks']

    # log inputs
    logger.info('project: {}'.format(project))
    logger.info('master_ids: {}'.format(master_ids))
    logger.info('slave_ids: {}'.format(slave_ids))
    logger.info('subswaths: {}'.format(ctx['swathnum']))
    logger.info('azimuth_looks: {}'.format(azimuth_looks))
    logger.info('range_looks: {}'.format(range_looks))
    logger.info('filter_strength: {}'.format(filter_strength))
    logger.info('precise_orbit_only: {}'.format(precise_orbit_only))
    logger.info('direction : {}'.format(direction))
    logger.info('platform : {}'.format(platform))
    logger.info('direction : {}'.format(direction))
    logger.info('platform : {}'.format(platform))

    logger.info('master_zip_file : {}'.format(master_zip_file))
    logger.info('slave_zip_file : {}'.format(slave_zip_file))
    logger.info('master_orbit_file : {}'.format(master_orbit_file))
    logger.info('slave_orbit_file : {}'.format(slave_orbit_file))

    logger.info(f'Using azimuth_looks of {azimuth_looks}'
                f' and range_looks of {range_looks}')
    logger.info('STITCHED SWATHS')

    ctx['filter_strength'] = ctx.get('context', {}).get('filter_strength', 0.5)
    logger.info('Using filter_strength of %f' % ctx['filter_strength'])

    logger.info('\nContext \n')
    logger.info(json.dumps(ctx, indent=4, sort_keys=True))

    # Check if ifg_name exists
    version = get_version()
    temp_ifg_id = get_temp_id(ctx, version)

    TESTING = ctx.get('testing', False)
    if not TESTING:
        if check_ifg_status_by_hash_version(new_ifg_hash, get_version()):
            err = "S1-GUNW IFG Found : %s" % temp_ifg_id
            logger.info(err)
            raise RuntimeError(err)

        logger.info('\n'
                    f'{DATASET_KEY} ifg cfg NOT Found:'
                    f'{temp_ifg_id}.\nProceeding ....\n')

    logger.debug('Warning: We assume that the zip paths are '
                 'in the current working directory with the other data')
    zip_paths = list(Path('.').glob('S1*_IW_SLC__*.zip'))
    logger.info(f'There are {len(zip_paths)} slcs to unzip')
    if len(zip_paths) == 0:
        err_msg = 'No SLC files to Unzip!'
        raise RuntimeError(err_msg)
    list(map(unzip_annotation_xmls, zip_paths))

    # get polarization values
    master_pol = get_pol_data_from_slcs(ctx['master_zip_file'])
    slave_pol = get_pol_data_from_slcs(ctx['slave_zip_file'])
    if master_pol == slave_pol:
        match_pol = master_pol
    else:
        err_msg = ('Reference and Secondary Polarization are NOT SAME\n'
                   f'Reference Polarization : {master_pol}\n'
                   f'Secondary Polarization : {slave_pol}')
        raise RuntimeError(err_msg)

    # get union bbox
    logger.info('Determining envelope bbox from SLC swaths.')

    envelope_dict = get_envelope_from_all_slcs()
    bbox = [envelope_dict['ymin'],
            envelope_dict['ymax'],
            envelope_dict['xmin'],
            envelope_dict['xmax'],
            ]
    bbox_json = {'envelope': bbox}
    json.dump(bbox_json,
              open('bbox.json', 'w'),
              indent=2)

    logger.info(f'bbox: {json.dumps(bbox_json, indent=2)}')

    # get dataset version and set dataset ID
    version = get_version()

    # get endpoint configurations

    # get DEM configuration
    dem_type = ctx['dem_type']
    logger.info(f'dem_type: {dem_type}')
    dem_type_simple = None
    dem_url = SETTINGS_DICT['ARIA_DEM_URL']
    # This is not in our settings currently
    srtm3_dem_url = SETTINGS_DICT.get('ARIA_SRTM3_DEM_URL')
    ned1_dem_url = SETTINGS_DICT['ARIA_NED1_DEM_URL']
    ned13_dem_url = SETTINGS_DICT['ARIA_NED13_DEM_URL']

    preprocess_dem_dir = 'preprocess_dem'
    geocode_dem_dir = 'geocode_dem'

    # download project specific preprocess DEM

    # get DEM bbox
    dem_S, dem_N, dem_W, dem_E = bbox
    dem_S = int(math.floor(dem_S))
    dem_N = int(math.ceil(dem_N))
    dem_W = int(math.floor(dem_W))
    dem_E = int(math.ceil(dem_E))

    logger.info('DEM TYPE : %s' % dem_type)
    if dem_type.startswith('SRTM'):
        dem_type_simple = 'SRTM'
        if dem_type.startswith('SRTM3'):
            dem_url = srtm3_dem_url
            dem_type_simple = 'SRTM3'

        dem_cmd = [
            '{}/applications/dem.py'.format(os.environ['ISCE_HOME']), '-a',
            'stitch', '-b', '{} {} {} {}'.format(dem_S,
                                                 dem_N,
                                                 dem_W,
                                                 dem_E),
            '-r', '-s', '1', '-f', '-x', '-c', '-n', dem_user, '-w',
            dem_pass, '-u', dem_url
        ]
        dem_cmd_line = ' '.join(dem_cmd)
        logger.info('Calling dem.py: {}'.format(dem_cmd_line))
        check_call(dem_cmd_line, shell=True)
        preprocess_dem_file = glob('*.dem.wgs84')[0]

    else:
        if dem_type == 'NED1':
            dem_url = ned1_dem_url
            dem_type_simple = 'NED1'
        elif dem_type.startswith('NED13'):
            dem_url = ned13_dem_url
            dem_type_simple = 'NED13'
        else:
            raise RuntimeError('Unknown dem type %s.' % dem_type)
        if dem_type == 'NED13-downsampled':
            downsample_option = '-d 33%'
        else:
            downsample_option = ''

        dem_S = dem_S - 1 if dem_S > -89 else dem_S
        dem_N = dem_N + 1 if dem_N < 89 else dem_N
        dem_W = dem_W - 1 if dem_W > -179 else dem_W
        dem_E = dem_E + 1 if dem_E < 179 else dem_E

        topsApp_util_dir = os.environ['TOPSAPP'] + '/topsApp_utils'
        dem_cmd = [
            '{}/ned_dem.py'.format(topsApp_util_dir), '-a',
            'stitch', '-b', '{} {} {} {}'.format(dem_S,
                                                 dem_N,
                                                 dem_W,
                                                 dem_E),
            downsample_option, '-u', dem_user, '-p', dem_pass, dem_url
        ]
        dem_cmd_line = ' '.join(dem_cmd)
        logger.info('Calling ned_dem.py: {}'.format(dem_cmd_line))
        check_call(dem_cmd_line, shell=True)
        preprocess_dem_file = 'stitched.dem'

    logger.info('Preprocess DEM file: {}'.format(preprocess_dem_file))

    preprocess_dem_dir = '{}_{}'.format(dem_type_simple, preprocess_dem_dir)

    logger.info('dem_type : %s preprocess_dem_dir : %s' % (dem_type,
                                                           preprocess_dem_dir))
    if dem_type.startswith('NED'):
        move_dem_separate_dir_NED(preprocess_dem_dir)
    elif dem_type.startswith('SRTM'):
        move_dem_separate_dir_SRTM(preprocess_dem_dir)
    else:
        move_dem_separate_dir(preprocess_dem_dir)

    preprocess_dem_file = os.path.join(preprocess_dem_dir, preprocess_dem_file)
    logger.info('Using Preprocess DEM file: {}'.format(preprocess_dem_file))

    # fix file path in Preprocess DEM xml
    fix_cmd = [
        '{}/applications/fixImageXml.py'.format(os.environ['ISCE_HOME']),
        '-i', preprocess_dem_file, '--full'
    ]
    fix_cmd_line = ' '.join(fix_cmd)
    logger.info('Calling fixImageXml.py: {}'.format(fix_cmd_line))
    check_call(fix_cmd_line, shell=True)

    preprocess_vrt_file = ''
    if dem_type.startswith('SRTM'):
        glob_pattern = os.path.join(preprocess_dem_dir, '*.dem.wgs84.vrt')
        preprocess_vrt_file = glob(glob_pattern)[0]
    elif dem_type.startswith('NED1'):
        preprocess_vrt_file = os.path.join(preprocess_dem_dir,
                                           'stitched.dem.vrt')
        logger.info('preprocess_vrt_file : %s' % preprocess_vrt_file)
    else:
        raise RuntimeError('Unknown dem type %s.' % dem_type)

    if not os.path.isfile(preprocess_vrt_file):
        logger.info('%s does not exists. Exiting')

    geocode_dem_dir = os.path.join(preprocess_dem_dir,
                                   f'Coarse_{dem_type_simple}_preprocess_dem')
    create_dir(geocode_dem_dir)
    dem_cmd = [
        '{}/applications/downsampleDEM.py'.format(os.environ['ISCE_HOME']),
        '-i',
        '{}'.format(preprocess_vrt_file), '-rsec', '3'
    ]
    dem_cmd_line = ' '.join(dem_cmd)
    logger.info('Calling downsampleDEM.py: {}'.format(dem_cmd_line))
    check_call(dem_cmd_line, shell=True)
    geocode_dem_file = ''

    logger.info('geocode_dem_dir : {}'.format(geocode_dem_dir))
    if dem_type.startswith('SRTM'):
        glob_pattern = os.path.join(geocode_dem_dir, '*.dem.wgs84')
        geocode_dem_file = glob(glob_pattern)[0]
    elif dem_type.startswith('NED1'):
        geocode_dem_file = os.path.join(geocode_dem_dir, 'stitched.dem')
    logger.info('Using Geocode DEM file: {}'.format(geocode_dem_file))

    checkBurstError()

    # fix file path in Geocoding DEM xml
    fix_cmd = [
        '{}/applications/fixImageXml.py'.format(os.environ['ISCE_HOME']),
        '-i', geocode_dem_file, '--full'
    ]
    fix_cmd_line = ' '.join(fix_cmd)
    logger.info('Calling fixImageXml.py: {}'.format(fix_cmd_line))
    check_call(fix_cmd_line, shell=True)

    # download auciliary calibration files
    fetch_aux_cal('aux_cal', False)

    # ESD Computations
    # ESD is by dafault turned off
    do_esd = ctx.get('do_esd', False)
    logger.info(f'ESD computations are {"ON" if do_esd else "OFF"}')

    # create initial input xml
    esd_coh_thresh = 0.85 if do_esd else - 1.
    master_orbit = ctx['master_orbit_file']
    slave_orbit = ctx['slave_orbit_file']
    region_of_interest_str = str(ctx.get('region_of_interest', bbox))

    TEMPLATE_DICT = dict(MASTER_SAFE_DIR=master_zip_file,
                         SLAVE_SAFE_DIR=slave_zip_file,
                         MASTER_ORBIT_FILE=master_orbit,
                         SLAVE_ORBIT_FILE=slave_orbit,
                         DEM_FILE=preprocess_dem_file,
                         GEOCODE_DEM_FILE=geocode_dem_file,
                         SWATHNUM=str(ctx['swathnum']),
                         AZIMUTH_LOOKS=ctx['azimuth_looks'],
                         RANGE_LOOKS=ctx['range_looks'],
                         FILTER_STRENGTH=ctx['filter_strength'],
                         REGION_OF_INTEREST=region_of_interest_str,
                         USE_VIRTUAL_FILES=True,
                         DO_ESD=do_esd,
                         ESD_COHERENCE_THRESHOLD=esd_coh_thresh)

    def create_input_xml(template_dict,
                         out_xml,
                         template_file=TEMPLATE_FILE):
        with open(template_file) as f:
            template = Template(f.read())
        template = template.substitute(**template_dict)
        with open(out_xml, 'w') as f:
            f.write(template)
        return out_xml

    create_input_xml(TEMPLATE_DICT, 'topsApp.xml')

    # get the time before stating topsApp.py
    topsApp_start_time = datetime.now()
    logger.info('TopsApp Start Time : {}'.format(topsApp_start_time))

    # run topsApp to prepesd step
    topsapp_cmd = [
        'topsApp.py', '--steps', '--end=prepesd',
    ]
    topsapp_cmd_line = ' '.join(topsapp_cmd)
    logger.info(f'Calling topsApp.py to prepesd step: {topsapp_cmd_line}')
    check_call(topsapp_cmd_line, shell=True)

    # iterate over ESD coherence thresholds
    esd_coh_increment = 0.05
    esd_coh_min = 0.5

    topsapp_cmd = [
        'topsApp.py', '--steps', '--dostep=esd',
    ]
    topsapp_cmd_line = ' '.join(topsapp_cmd)
    check_call(topsapp_cmd_line, shell=True)

    template_esd = TEMPLATE_DICT.copy()
    while do_esd:
        logger.info('Calling topsApp.py on esd step '
                    f'with ESD coherence threshold: {esd_coh_thresh}')
        try:
            check_call(topsapp_cmd_line, shell=True)
            break
        except CalledProcessError:
            logger.info('ESD filtering failed with coherence threshold: '
                        f'{esd_coh_thresh}')
            esd_coh_thresh = round(esd_coh_thresh - esd_coh_increment, 2)
            if esd_coh_thresh < esd_coh_min:
                logger.info('Disabling ESD filtering.')
                do_esd = False
                template_esd['do_esd'] = False
                create_input_xml(template_esd, 'topsApp.xml')
                break
            logger.info('Reducing ESD coherence threshold to: '
                        f'{esd_coh_thresh}')
            logger.info('Creating topsApp.xml with'
                        f'ESD coherence threshold: {esd_coh_thresh}')
            create_input_xml(template_esd, 'topsApp.xml')

    # run topsApp from rangecoreg to geocode
    topsapp_cmd = [
        'topsApp.py', '--steps', '--start=rangecoreg', '--end=geocode',
    ]
    topsapp_cmd_line = ' '.join(topsapp_cmd)
    logger.info(f'Calling topsApp.py to geocode step: {topsapp_cmd_line}')

    checkBurstError()

    check_call(topsapp_cmd_line, shell=True)

    # topsApp End Time
    topsApp_end_time = datetime.now()
    logger.info('TopsApp End Time : {}'.format(topsApp_end_time))

    topsApp_run_time = topsApp_end_time - topsApp_start_time
    logger.info('New TopsApp Run Time : {}'.format(topsApp_run_time))

    swath_list = ctx['swathnum'].copy()

    # get radian value for 5-cm wrap. As it is same for all swath,
    # we will use swathnum = 1
    rt = parse('master/IW{}.xml'.format(swath_list[0]))
    wv = eval(rt.xpath(".//property[@name='radarwavelength']/value/text()")[0])
    rad = 4 * np.pi * .05 / wv
    logger.info('Radian value for 5-cm wrap is: {}'.format(rad))

    # create id and product directory

    output = get_tops_metadata('fine_interferogram')
    sensing_start = output['sensingStart']
    sensing_stop = output['sensingStop']
    logger.info('sensing_start : %s' % sensing_start)
    logger.info('sensing_stop : %s' % sensing_stop)

    acq_center_time = get_center_time(sensing_start, sensing_stop)

    ifg_hash = ctx['new_ifg_hash']
    direction = ctx['direction']
    platform = ctx['platform']
    orbit_type = ctx['orbit_type']
    track = ctx['track_number']
    slave_ifg_dt = ctx['slc_slave_dt']
    master_ifg_dt = ctx['slc_master_dt']
    lats = get_geocoded_lats('merged/filt_topophase.unw.geo.vrt')

    logger.info(f'lats : {lats}')
    logger.info(f'max(lats): {max(lats)}: {convert_number(max(lats))}')
    logger.info(f'min(lats): {min(lats)}: {convert_number(min(lats))}')

    sorted_lats_temp = sorted(lats)[-2]
    num = convert_number(sorted_lats_temp)
    logger.info(f'sorted(lats)[-2] : {sorted_lats_temp}: {num}')
    sorted_lats_temp = sorted(lats)[1]
    num = convert_number(sorted_lats_temp)
    logger.info(f'sorted(lats)[1]{sorted_lats_temp} : {num}')

    sat_direction = 'D'
    logger.info('sat_direction : {}'.format(sat_direction))

    west_lat = '{}_{}'.format(convert_number(sorted(lats)[-2]),
                              convert_number(min(lats)))

    if direction.lower() == 'asc':
        sat_direction = 'A'
        west_lat = '{}_{}'.format(convert_number(max(lats)),
                                  convert_number(sorted(lats)[1]))

    ifg_hash = ifg_hash[0:4]
    logger.info('slc_master_dt : %s,slc_slave_dt : %s' % (slc_master_dt,
                                                          slc_slave_dt))
    id_tmpl_merged = 'S1-GUNW-MERGED_R{}_M{:d}S{:d}_TN{:03d}_{}-{}_s123-{}-{}'
    ifg_id_merged = id_tmpl_merged.format('M',
                                          len(master_ids),
                                          len(slave_ids),
                                          track,
                                          master_ifg_dt,
                                          slave_ifg_dt,
                                          orbit_type,
                                          ifg_hash)
    logger.info('ifg_id_merged : %s' % ifg_id_merged)

    ifg_id = IFG_ID_SP_TMPL.format(sat_direction,
                                   'R',
                                   track,
                                   master_ifg_dt.split('T')[0],
                                   slave_ifg_dt.split('T')[0],
                                   acq_center_time,
                                   west_lat, ifg_hash,
                                   version.replace('.', '_'))
    id = ifg_id

    logger.info('id : %s' % ifg_id)
    logger.info('ifg_id_merged : %s' % ifg_id_merged)

    prod_dir = ifg_id

    logger.info('prod_dir : %s' % prod_dir)

    os.makedirs(prod_dir, 0o755)

    # make metadata geocube
    os.chdir('merged')
    topsApp_path = os.environ['TOPSAPP']
    mgc_cmd = [f'{topsApp_path}/topsApp_utils/makeGeocube.py',
               '-m', '../master',
               '-s', '../slave',
               '-o', 'metadata.h5'
               ]
    mgc_cmd_line = ' '.join(mgc_cmd)
    logger.info('Calling makeGeocube.py: {}'.format(mgc_cmd_line))
    check_call(mgc_cmd_line, shell=True)

    # create standard product packaging
    std_prod_file = '{}.nc'.format(ifg_id)

    with open(os.path.join(BASE_PATH, 'tops_groups.json')) as f:
        std_cfg = json.load(f)
    std_cfg['filename'] = std_prod_file
    with open('tops_groups.json', 'w') as f:
        json.dump(std_cfg, f, indent=2, sort_keys=True)
    std_cmd = [
        '{}/topsApp_utils/standard_product_packaging.py'.format(BASE_PATH)
    ]
    std_cmd_line = ' '.join(std_cmd)
    logger.info(f'Calling standard_product_packaging.py: {std_cmd_line}')
    check_call(std_cmd_line, shell=True)

    # chdir back up to work directory
    os.chdir(cwd)

    # move standard product to product directory
    shutil.move(os.path.join('merged', std_prod_file), prod_dir)

    # generate GDAL (ENVI) headers and move to product directory
    raster_prods = (
        'merged/topophase.cor',
        'merged/topophase.flat',
        'merged/filt_topophase.flat',
        'merged/filt_topophase.unw',
        'merged/filt_topophase.unw.conncomp',
        'merged/phsig.cor',
        'merged/los.rdr',
        'merged/dem.crop',
    )
    for i in raster_prods:
        # radar-coded products
        call_noerr('isce2gis.py envi -i {}'.format(i))

        # geo-coded products
        j = '{}.geo'.format(i)
        if not os.path.exists(j):
            continue
        call_noerr('isce2gis.py envi -i {}'.format(j))

    # save other files to product directory
    shutil.copyfile('_context.json', os.path.join(prod_dir,
                                                  f'{ifg_id}.context.json'))

    fine_int_xmls = []
    for swathnum in swath_list:
        fine_int_xmls.append('fine_interferogram/IW{}.xml'.format(swathnum))

    # get water mask configuration
    wbd_url = SETTINGS_DICT['ARIA_WBD_URL']

    # get DEM bbox and add slop
    dem_S, dem_N, dem_W, dem_E = bbox
    dem_S = int(math.floor(dem_S))
    dem_N = int(math.ceil(dem_N))
    dem_W = int(math.floor(dem_W))
    dem_E = int(math.ceil(dem_E))
    dem_S = dem_S - 1 if dem_S > -89 else dem_S
    dem_N = dem_N + 1 if dem_N < 89 else dem_N
    dem_W = dem_W - 1 if dem_W > -179 else dem_W
    dem_E = dem_E + 1 if dem_E < 179 else dem_E

    # get water mask
    fp = open('wbdStitcher.xml', 'w')
    fp.write("<stitcher>\n")
    fp.write("    <component name='wbdstitcher'>\n")
    fp.write("        <component name='wbd stitcher'>\n")
    fp.write("            <property name='url'>\n")
    fp.write("                <value>https://urlToRepository</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='action'>\n")
    fp.write("                <value>stitch</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='directory'>\n")
    fp.write("                <value>outputdir</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='bbox'>\n")
    fp.write("                <value>[33,36,-119,-117]</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='keepWbds'>\n")
    fp.write("                <value>False</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='noFilling'>\n")
    fp.write("                <value>False</value>\n")
    fp.write("            </property>\n")
    fp.write("            <property name='nodata'>\n")
    fp.write("                <value>-1</value>\n")
    fp.write("            </property>\n")
    fp.write("        </component>\n")
    fp.write("    </component>\n")
    fp.write("</stitcher>")
    fp.close()
    wbd_file = 'wbdmask.wbd'
    wbd_cmd = [f'{os.environ["ISCE_HOME"]}/applications/wbdStitcher.py',
               'wbdStitcher.xml',
               'wbdstitcher.wbdstitcher.bbox=[{},{},{},{}]'.format(dem_S,
                                                                   dem_N,
                                                                   dem_W,
                                                                   dem_E),
               f'wbdstitcher.wbdstitcher.outputfile={wbd_file}',
               'wbdstitcher.wbdstitcher.url={}'.format(wbd_url)
               ]
    wbd_cmd_line = ' '.join(wbd_cmd)
    logger.info('Calling wbdStitcher.py: {}'.format(wbd_cmd_line))
    try:
        check_call(wbd_cmd_line, shell=True)
    except Exception as e:
        logger.info(str(e))

    # get product image and size info
    vrt_prod = get_image('merged/filt_topophase.unw.geo.xml')
    vrt_prod_size = get_size(vrt_prod)
    flat_vrt_prod = get_image('merged/filt_topophase.flat.geo.xml')
    flat_vrt_prod_size = get_size(flat_vrt_prod)

    # get water mask image and size info
    wbd_xml = '{}.xml'.format(wbd_file)
    wmask = get_image(wbd_xml)
    wmask_size = get_size(wmask)

    # determine downsample ratio and dowsample water mask
    denom = old_div(vrt_prod_size['lon']['delta'],
                    wmask_size['lon']['delta'])
    lon_rat = 1. / (denom) * 100
    denom = old_div(vrt_prod_size['lat']['delta'],
                    wmask_size['lat']['delta'])
    lat_rat = 1. / (denom) * 100
    logger.info('lon_rat/lat_rat: {} {}'.format(lon_rat, lat_rat))
    wbd_ds_file = 'wbdmask_ds.wbd'
    wbd_ds_vrt = 'wbdmask_ds.vrt'
    check_call(('gdal_translate -of ENVI '
                f'-outsize {lon_rat}% {lat_rat}% {wbd_file} {wbd_ds_file}'),
               shell=True)
    check_call('gdal_translate -of VRT {} {}'.format(wbd_ds_file, wbd_ds_vrt),
               shell=True)

    # update xml file for downsampled water mask
    wbd_ds_json = '{}.json'.format(wbd_ds_file)
    check_call('gdalinfo -json {} > {}'.format(wbd_ds_file, wbd_ds_json),
               shell=True)
    with open(wbd_ds_json) as f:
        info = json.load(f)
    with open(wbd_xml) as f:
        doc = parse(f)
    wbd_ds_xml = '{}.xml'.format(wbd_ds_file)

    res = doc.xpath(".//component[@name='coordinate1']"
                    "/property[@name='delta']/value")
    res[0].text = str(info['geoTransform'][1])

    res = doc.xpath(".//component[@name='coordinate1']"
                    "/property[@name='size']/value")
    res[0].text = str(info['size'][0])

    res = doc.xpath(".//component[@name='coordinate2']"
                    "/property[@name='delta']/value")
    res[0].text = str(info['geoTransform'][5])

    res = doc.xpath(".//component[@name='coordinate2']"
                    "/property[@name='size']/value")
    res[0].text = str(info['size'][1])

    res = doc.xpath(".//property[@name='width']/value")
    res[0].text = str(info['size'][0])

    res = doc.xpath(".//property[@name='length']/value")
    res[0].text = str(info['size'][1])

    res = doc.xpath(".//property[@name='metadata_location']/value")[0]
    res.text = wbd_ds_xml

    res = doc.xpath(".//property[@name='file_name']/value")
    res[0].text = wbd_ds_file

    for rm in doc.xpath(".//property[@name='extra_file_name']"):
        rm.getparent().remove(rm)
    doc.write(wbd_ds_xml)

    # get downsampled water mask image and size info
    wmask_ds = get_image(wbd_ds_xml)
    wmask_ds_size = get_size(wmask_ds)

    logger.info('vrt_prod.filename: {}'.format(vrt_prod.filename))
    logger.info('vrt_prod.bands: {}'.format(vrt_prod.bands))
    logger.info('vrt_prod size: {}'.format(vrt_prod_size))
    logger.info('wmask.filename: {}'.format(wmask.filename))
    logger.info('wmask.bands: {}'.format(wmask.bands))
    logger.info('wmask size: {}'.format(wmask_size))
    logger.info('wmask_ds.filename: {}'.format(wmask_ds.filename))
    logger.info('wmask_ds.bands: {}'.format(wmask_ds.bands))
    logger.info('wmask_ds size: {}'.format(wmask_ds_size))

    # crop the downsampled water mask
    wbd_cropped_file = 'wbdmask_cropped.wbd'
    wmask_cropped = crop_mask(vrt_prod, wmask_ds, wbd_cropped_file)
    logger.info('wmask_cropped shape: {}'.format(wmask_cropped.shape))

    # read in wrapped interferogram
    flat_vrt_prod_im = np.memmap(flat_vrt_prod.filename,
                                 dtype=flat_vrt_prod.toNumpyDataType(),
                                 mode='c',
                                 shape=(flat_vrt_prod_size['lat']['size'],
                                        flat_vrt_prod_size['lon']['size']))
    phase = np.angle(flat_vrt_prod_im)
    phase[phase == 0] = -10
    phase[wmask_cropped == -1] = -10

    # mask out water from the product data
    vrt_prod_shape = (vrt_prod_size['lat']['size'],
                      vrt_prod.bands,
                      vrt_prod_size['lon']['size'])
    vrt_prod_im = np.memmap(vrt_prod.filename,
                            dtype=vrt_prod.toNumpyDataType(),
                            mode='c', shape=vrt_prod_shape)
    im1 = vrt_prod_im[:, :, :]
    for i in range(vrt_prod.bands):
        im1_tmp = im1[:, i, :]
        im1_tmp[wmask_cropped == -1] = 0

    # read in connected component mask
    cc_vrt = 'merged/filt_topophase.unw.conncomp.geo.vrt'
    cc = gdal.Open(cc_vrt)
    cc_data = cc.ReadAsArray()
    cc = None
    logger.info('cc_data: {}'.format(cc_data))
    logger.info('cc_data shape: {}'.format(cc_data.shape))
    for i in range(vrt_prod.bands):
        im1_tmp = im1[:, i, :]
        im1_tmp[cc_data == 0] = 0
    phase[cc_data == 0] = -10

    # overwrite displacement with phase
    im1[:, 1, :] = phase

    # create masked product image
    masked_filt = 'filt_topophase.masked.unw.geo'
    masked_filt_xml = 'filt_topophase.masked.unw.geo.xml'
    tim = np.memmap(masked_filt,
                    dtype=vrt_prod.toNumpyDataType(),
                    mode='w+',
                    shape=vrt_prod_shape)
    tim[:, :, :] = im1
    im = Image()
    with open('merged/filt_topophase.unw.geo.xml') as f:
        doc = parse(f)
    doc.xpath(".//property[@name='file_name']/value")[0].text = masked_filt
    for rm in doc.xpath(".//property[@name='extra_file_name']"):
        rm.getparent().remove(rm)
    doc.write(masked_filt_xml)
    im.load(masked_filt_xml)
    latstart = vrt_prod_size['lat']['val']
    lonstart = vrt_prod_size['lon']['val']
    latsize = vrt_prod_size['lat']['size']
    lonsize = vrt_prod_size['lon']['size']
    latdelta = vrt_prod_size['lat']['delta']
    londelta = vrt_prod_size['lon']['delta']
    im.coord2.coordStart = latstart
    im.coord2.coordSize = latsize
    im.coord2.coordDelta = latdelta
    im.coord2.coordEnd = latstart + latsize*latdelta
    im.coord1.coordStart = lonstart
    im.coord1.coordSize = lonsize
    im.coord1.coordDelta = londelta
    im.coord1.coordEnd = lonstart + lonsize*londelta
    im.filename = masked_filt
    im.renderHdr()

    # mask out nodata values
    vrt_prod_file = 'filt_topophase.masked.unw.geo.vrt'
    vrt_prod_file_amp = 'filt_topophase.masked_nodata.unw.amp.geo.vrt'
    vrt_prod_file_dis = 'filt_topophase.masked_nodata.unw.dis.geo.vrt'
    cmd = (f'gdal_translate -of VRT -b 1 -a_nodata 0 {vrt_prod_file} '
           f'{vrt_prod_file_amp}')
    check_call(cmd, shell=True)

    cmd = (f'gdal_translate -of VRT -b 2 -a_nodata -10 {vrt_prod_file} '
           f'{vrt_prod_file_dis}')
    check_call(cmd, shell=True)

    # create interferogram tile layer
    tiles_dir = '{}/tiles'.format(prod_dir)
    topsApp_util_dir = os.environ['TOPSAPP'] + '/topsApp_utils'
    dis_layer = 'interferogram'
    tiler_cmd_tmpl = ('{}/create_tiles.py {} {}/{} '
                      '-b 1 -m hsv --clim_min {} --clim_max {} --nodata 0')
    check_call(tiler_cmd_tmpl.format(topsApp_util_dir,
                                     vrt_prod_file_dis,
                                     tiles_dir,
                                     dis_layer,
                                     -3.14,
                                     3.14),
               shell=True)

    # create browse images
    tif_file_dis = '{}.tif'.format(vrt_prod_file_dis)
    check_call('gdal_translate -of png -r average -tr '
               '0.00416666667 0.00416666667 '
               '{} {}/{}.interferogram.browse_coarse.png'.format(tif_file_dis,
                                                                 prod_dir,
                                                                 id),
               shell=True)
    check_call('gdal_translate -of png '
               '{} {}/{}.interferogram.browse_full.png'.format(tif_file_dis,
                                                               prod_dir,
                                                               id),
               shell=True)
    for i in glob('{}/{}.*.browse*.aux.xml'.format(prod_dir, id)):
        os.unlink(i)

    # extract metadata from master
    met_file = os.path.join(prod_dir, '{}.met.json'.format(id))
    frame_metadata_dir = os.environ['TOPSAPP'] + '/frameMetadata'
    extract_cmd_tmpl = ('{}/extractMetadata_standard_product.sh -i '
                        '{}/annotation/s1?-iw?-slc-{}-*.xml -o {}')
    check_call(extract_cmd_tmpl.format(frame_metadata_dir,
                                       master_zip_file[0].replace('.zip',
                                                                  '.SAFE'),
                                       master_pol,
                                       met_file),
               shell=True)

    # update met JSON
    if (('RESORB' in ctx['master_orbit_file']) or
       ('RESORB' in ctx['slave_orbit_file'])):
        orbit_type = 'resorb'
    else:
        orbit_type = 'poeorb'
    scene_count = min(len(master_zip_file), len(slave_zip_file))
    master_mission = MISSION_RE.search(master_zip_file[0]).group(1)
    slave_mission = MISSION_RE.search(slave_zip_file[0]).group(1)
    unw_vrt = 'filt_topophase.unw.geo.vrt'
    unw_xml = 'filt_topophase.unw.geo.xml'
    cmd_path = (f'{topsApp_util_dir}/update_met_json_standard_product.py')
    update_met_cmd = (cmd_path + ' {} {} "{}"'
                      ' {} {} {} "{}" {}/{} {}/{} {} {} {} {}')
    check_call(update_met_cmd.format(orbit_type, scene_count,
                                     ctx['swathnum'], master_mission,
                                     slave_mission, 'PICKLE',
                                     fine_int_xmls,
                                     'merged', unw_vrt,
                                     'merged', unw_xml,
                                     met_file, sensing_start,
                                     sensing_stop, std_prod_file), shell=True)

    # add master/slave ids and orbits to met JSON (per ASF request)
    master_ids = [i.replace('.zip', '') for i in ctx['master_zip_file']]
    slave_ids = [i.replace('.zip', '') for i in ctx['slave_zip_file']]
    master_rt = parse(f'master/IW{swath_list[0]}.xml')
    master_out = eval(master_rt.xpath(".//property[@name='orbitnumber']"
                                      "/value/text()")[0])
    master_orbit_number = master_out
    slave_rt = parse(f'slave/IW{swath_list[0]}.xml')
    slave_out = eval(slave_rt.xpath(".//property[@name='orbitnumber']"
                                    "/value/text()")[0])
    slave_orbit_number = slave_out
    with open(met_file) as f:
        md = json.load(f)
    md['reference_scenes'] = master_ids
    md['secondary_scenes'] = slave_ids
    md['orbitNumber'] = [master_orbit_number, slave_orbit_number]

    # add ESD coherence threshold
    md['esd_threshold'] = esd_coh_thresh

    # add range_looks and azimuth_looks to metadata for stitching purposes
    md['azimuth_looks'] = int(ctx['azimuth_looks'])
    md['range_looks'] = int(ctx['range_looks'])

    # add filter strength
    md['filter_strength'] = float(ctx['filter_strength'])
    md['union_geojson'] = ctx['union_geojson']

    # add dem_type
    md['dem_type'] = dem_type
    md['sensingStart'] = sensing_start
    md['sensingStop'] = sensing_stop
    md['tags'] = ['standard_product']
    md['polarization'] = match_pol.upper()
    md['reference_date'] = get_date_str(ctx['slc_master_dt'])
    md['secondary_date'] = get_date_str(ctx['slc_slave_dt'])
    md['full_id_hash'] = ctx['new_ifg_hash']
    md['system_version'] = ctx['system_version']

    try:
        if 'temporal_span' in md:
            logger.info(f'temporal_span is {md["temporal_span"]}')
        tb = getTemporalSpanInDays(get_time_str(slc_master_dt),
                                   get_time_str(slc_slave_dt))
        md['temporal_span'] = tb
        logger.info('temporal_span based on slc data: %s' % tb)
    except Exception as err:
        logger.info('Error in getTemporalSpanInDays : %s' % str(err))

    # update met files key to have python style naming
    md = update_met(md)

    # topsApp End Time
    complete_end_time = datetime.now()
    logger.info('TopsApp End Time : {}'.format(complete_end_time))

    complete_run_time = complete_end_time - complete_start_time
    logger.info('New TopsApp Run Time : {}'.format(complete_run_time))

    # Include runtime stats in metadata file
    md['runtime_in_seconds'] = round(complete_run_time.total_seconds(), 2)
    root_directory = Path('.')
    nbytes = sum(f.stat().st_size
                 for f in root_directory.glob('**/*') if f.is_file())
    md['scratch_disk_at_completion_bytes'] = nbytes

    # write met json
    logger.info('creating met file : %s' % met_file)
    with open(met_file, 'w') as f:
        json.dump(md, f, indent=2)

    # generate dataset JSON
    ds_file = os.path.join(prod_dir, '{}.dataset.json'.format(id))
    logger.info('creating dataset file : %s' % ds_file)
    create_dataset_json(id, version, met_file, ds_file)

    nc_file = os.path.join(prod_dir, '{}.nc'.format(id))
    nc_file_md5 = get_md5_from_file(nc_file)
    nc_checksum_file = os.path.join(prod_dir, '{}.nc.md5'.format(id))
    logger.info('nc_file_md5 : {}'.format(nc_file_md5))
    with open(nc_checksum_file, 'w') as f:
        f.write(nc_file_md5)


def updateErrorFiles(msg):
    msg = msg.strip()

    with open('_alt_error.txt', 'w') as f:
        f.write(f'{msg}\n')
    with open('_alt_traceback.txt', 'w') as f:
        f.write('%s\n' % traceback.format_exc())


if __name__ == '__main__':
    wd = os.getcwd()

    try:
        status = main()
        checkBurstError()
    except Exception as e:
        max_retry = 3
        ctx_file = os.path.join(wd, '_context.json')

        with open(ctx_file) as f:
            ctx = json.load(f)

        TESTING = ctx.get('testing', False)
        if not TESTING:
            job_file = os.path.join(wd, '_job.json')
            with open(job_file) as f:
                job = json.load(f)
            retry_count = int(job.get('retry_count', 0))
            if retry_count < max_retry:
                ctx['_triage_disabled'] = True

        ctx['_triage_additional_globs'] = ['S1-IFG*',
                                           'AOI_*',
                                           'celeryconfig.py',
                                           '*.json',
                                           '*.log',
                                           '*.txt']

        # If testing, then do NOT rewrite context.json
        if not TESTING:
            with open(ctx_file, 'w') as f:
                json.dump(ctx, f, sort_keys=True, indent=2)

        found = False
        msg = 'cannot continue for interferometry applications'
        found, line = fileContainsMsg(LOG_NAME, msg)
        if found:
            logger.info(f'Found Error : {line}')
            updateErrorFiles(line.strip())

        if not found:
            msg = 'Exception: Could not determine a suitable burst offset'
            found, line = fileContainsMsg(LOG_NAME, msg)
            if found:
                logger.info('Found Error : %s' % line.strip())
                updateErrorFiles(line.strip())

        if not found:
            updateErrorFiles(str(e))

        raise

    sys.exit(status)
