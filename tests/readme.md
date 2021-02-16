# Coseismic TopsApp PGE

This describes how to test and possibly interact with the PGE locally.


# Instructions for generic setup

1. Navigate to the terminal to this repo.
2. `docker build -f docker/Dockerfile -t standard_product_img .`
3.  Write a `.netrc` in this directory with the earthdata credentials (this will be copied to the container during tests).
   ```
   machine 100.67.35.28 login USERNAME password PASSWORD
   macdef init
   ```
   You will also want to add these credentials to your *actual* `.netrc` to download data files.
5. Get `settings.conf` from mozart and copy into `topsApp_pge/conf/settings.conf`.
6. Get data as instructed below. Must get
   1. Use the `_context.json` as a template (just copy one) and modify as recommended below.
   2. SLCs found in `_context.json` must be download
   3. Ideally figure out small region of interest
7. From this repo, run your docker container mounting the topsApp PGE and this data repo. Here is my command: `docker run -ti -p 1313:1313 -v $PWD:/home/ops/topsApp_pge standard_product_img`
8. Run `startup.sh` to use jupyter and run individual shell scripts from the terminal

## Modifying the context.json

## Geting Data

### Option 1

Test the PGE using the face tool (this requires some work to see which SLCs are available and you will have to dicuss with the pipeline operator). After launching it, copy the `_context.json` file from `work_directory` in the the job manager and use this to download the SLCs locally.

### Option 2

Use topsApp data and the Notebook [0-Rewrite-context.ipynb](0-Rewrite-context.ipynb)

### Modifying Context.json

Use some basic GIS to create a subset in the middle of the image and use only the middle swath to make the testing move more quickly. For example:

```
"swathnum": [2],
"testing": true,
"region_of_interest":
```

# Interactive debugging

Navigate terminal to the `<path of topsApp_pge>`.

`docker run -ti -p 1313:1313 -v $PWD:/home/ops/topsApp_pge standard_product_img`



## Jupyter

1. `tmux new -s jupyter`
2. `jupyter notebook --ip 0.0.0.0 --no-browser --allow-root --port 1313`

If running container remotely make sure you copy ports per [here]() i.e

```
ssh -N -L localhost:1313:localhost:1313 <username>@<host>
```

## From terminal

1. `/home/ops/coseismic-topsApp/create_standard_coseismic_product_s1.sh`