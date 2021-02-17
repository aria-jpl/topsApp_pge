# Coseismic TopsApp PGE

This describes how to test and possibly interact with the PGE locally.


# Instructions for generic setup

1. Navigate to the terminal to this repo.
2. `docker build -f docker/Dockerfile -t standard_product_img .` We assume this particular tag, i.e. `standard_product_img` in the tests and the other instructions. Modify at your own risk.
3.  Write a `.netrc` in this directory with the earthdata credentials (this will be copied to the container during tests. Also use your SSO credentials and add: `machine 100.67.35.28 login USERNAME password PASSWORD macdef init`. You will also want to add these credentials to your *actual*.netrc` to download data files in case you want to download files outside a docker container.
4. Get `settings.conf` from mozart and copy into `topsApp_pge/conf/settings.conf`. Modify as needed for local setup.
5. Get data as instructed below.
6. For running tests, run from the `tests` directory:

   `docker-compose -f coseismic_standard_product_pipeline_1/docker-compose.yaml run test`

   or more generically

   `docker-compose -f <direcotry of test>/docker-compose.yaml run test`.

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

## Modifying Context.json to reduce runtime

Our tests as indicated above are only applied to a region of interest using the ISCE topsApp option and a specific swath (there are swaths `1, 2, 3` and we select `2` for the tests).

Using some basic GIS, we look at the swath footprints and create a subset in the middle of the image . For example:

```
"swathnum": [2],
"testing": true,
"region_of_interest": [South, North, East, West]
```

# Interactive debugging

1. From this repo, run your docker container mounting the entire repo via `docker run -ti -p 1313:1313 -v $PWD:/home/ops/topsApp_pge standard_product_img`. *Note*: normally the container has the current git version (or the Jenkins build on the CI/CD infrastructure), but mounting the local version ensures the container is using the up-to-date code.
2.  Run `cd tests && bash interactive_startup.sh` to use jupyter and run individual shell scripts from the terminal. *Note*: the interactive startup takes time because you need to change permissions of the conda container to be able to install jupyter. At some point, we should do something about this in the build to make such changes easier.



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