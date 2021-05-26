# Coseismic TopsApp PGE

This describes how to test and possibly interact with the PGE locally. Note there was care taken so that these tests would as closely mirror operational runs as possible so that deploying any changes could be tested locally first.


# Instructions for generic setup

1. In a terminal, Navigate to this repo.
2. `docker build -f docker/Dockerfile -t standard_product_img .` We assume this particular tag, i.e. `standard_product_img` in the tests and the other instructions. Modify at your own risk.
3. Get `settings.conf` from mozart and copy into `topsApp_pge/conf/settings.conf`. You will need to add two rows related to Elastic Search credentials:
   ```
   ES_USERNAME=<ES_USERNAME>
   ES_PASSWORD=<ES_PASSWORD>
   ```
   There may be URLS that need to be modified for local setup including the `GRQ_URL` the `:9200` should be removed in my testing. As an aside, the local and operational function of these scripts should both be handled. For example, if not `ES_USERNAME` is supplied then `None` is used for Elastic Seach queries, which will work on AWS clusters. Similarly, the `GRQ_URL` should be updated on the AWS instances as this URL will be slightly different.
4. Create a netrc in topsApp repo with (unfortunately we use two different libraries for accessing elastics search):
   ```
   machine 100.67.35.28 login <USER> password <PSWRD>
   macdef init
   ```
5. Get data as instructed below.
6. For running tests, run from the `tests` directory:

   `docker-compose -f coseismic_standard_product_pipeline_1/docker-compose.yaml run test`

   or more generically

   `docker-compose -f <direcotry of test>/docker-compose.yaml run test`.

   If this is built on a computer in which docker privileges is different than user privileges, then use the following:

   `docker-compose -f coseismic_standard_product_pipeline_1/docker-compose.yaml run --user $UID:$GID test`

   This ensures the mounted volume and the products are written to the user who calls the compose command (docker by default calls root).

Some notes:

1. the tests are run on a `region_of_interest` and using only a 1 swath. This significantly reduces the runtime to make testing quicker. See below for details.
2. The test directories with `_full` indicate no such region of interest and swath restrictions were applied.
3. I had to specify a version of the `docker-compose.yaml` as the linux box used for testing had a slightly older version of the `docker-compose`.

# Obtaining Data for Tests

Navigate to `tests/coseismic_standard_product_pipeline_1` and run:

1. `python download_asf_slcs_1.py`
2. `bash download_eofs_1.py`.

Similarly navigate to `tests/coseismic_standard_product_pipeline_2` and replace the above commands `1` with `2`.

## Symbolic links for tests

Currently, all the tests use the two datasets from `coseismic_standard_product_pipeline_1/2`. To avoid unnecessary duplication, the docker commands create symbolic links during runtime. Note the symbolic links will be seen in the test directories but only be valid within docker containers. In other words, the symbolic links will not correctly work in your normal OS.


# Adding Additional Tests

To add additional end-to-end tests with different data one generally needs:
   1. A `_context.json` with the master/slave (or primary/secondary) image names correctly populated. Although the `_context.json` is long, only these ids and zip file names are needed and effectively one can copy and paste them in. I have generally obtained these files directly from TOSCA.
   2. SLCs  download. I used the `list` search through ASF.
   3. And preferably, determine a small region of interest to reduce runtime
   4. Make sure to add `local_test` as `true` in the `_context.json` if you are going to test deduplication and look up in our ES database.

## Modifying Context.json to reduce runtime

Our tests as indicated above are only applied to a region of interest using the ISCE topsApp option and a specific swath (there are swaths `1, 2, 3` and we select `2` for the tests).

Using some basic GIS, we look at the swath footprints and create a subset in the middle of the image . For example:

```
"swathnum": [2],
"testing": true,
"region_of_interest": [South, North, East, West]
"local_test": true
```
Note the last entry is for "short circuiting" tests or tests that use an actual `_context.json` from the system.

# Interactive debugging

1. From this repo, run your docker container mounting the entire repo via `docker run -ti -p 1313:1313 -v $PWD:/home/ops/topsApp_pge standard_product_img`. *Note*: normally the container has the current git version (or the Jenkins build on the CI/CD infrastructure), but mounting the local version ensures the container is using the up-to-date code.
2.  Run `cd tests && source interactive-startup.sh` to use jupyter and run individual shell scripts from the terminal. *Note*: the interactive startup takes time because you need to change permissions of the conda container to be able to install jupyter. At some point, we should do something about this in the build to make such changes easier.



## Jupyter

1. `tmux new -s jupyter`
2. `jupyter notebook --ip 0.0.0.0 --no-browser --allow-root --port 1313`

If running container remotely make sure you copy ports per [here]() i.e

```
ssh -N -L localhost:1313:localhost:1313 <username>@<host>
```

## From terminal of a docker container

1. Copy the bash commands from a `docker-compose.yaml`

Here is an example:

```
yes | cp -rf /home/ops/topsApp_pge/.netrc /home/ops/.netrc
&& cd /home/ops/topsApp_pge/tests/standard_product_pipeline_1
&& source symbolic_link_data_1.sh
&& /home/ops/topsApp_pge/create_standard_product_s1.sh
```

# Logging

A logger's file handle is not written to the volume until it is closed (similar to `gdal`'s dataset). As such, if you were to inspect the log for the relevant job it would be empty. At least it was for me until running `logging.shutdown()` per this [suggestion](https://stackoverflow.com/questions/15435652/python-does-not-release-filehandles-to-logfile). Interestingly, if you copy the log while it is open, it's current contents are copied and you can view the log state.