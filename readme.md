# topsApp_pge

This repo represents the topsApp Product Generation Executable (PGE) for the [TopsApp](https://github.com/isce-framework/isce2-docs/blob/master/Notebooks/UNAVCO_2020/TOPS/topsApp.ipynb) portion of the standard product pipeline generating interferograms from Sentinel-1.

This code was primarily written by [Mohammed Karim](https://github.com/mkarim2017) and [David Bekaert](https://github.com/dbekaert). The original code lives in the [ariamh repo](https://github.com/aria-jpl/ariamh) (along with other PGEs).

This code was reorganized so that the same python script could be used for the following two pipelines:

1. `coseismic`
2. `standard-product`

The script uses information from the `job-spec` of the PGE to perform the processing relevant to that pipeline (note there are two pairs of `job-spec` and `hysds-io` files in the `docker` directory corresponding to each pipelines PGE). The `job-spec` metadata is recorded within the `_context.json` per general HySDS operations.

To ensure jobs are not erroneously run using datasets across pipelines, we also check the machine tags of the `ifg-cfg` datasets used to create the `_context.json` to ensure the input datasets were slinged by the correct pipeline.

## Installation

The best to test a build is via the Dockerfile. Specifically from the terminal, navigate to this repo and then build the docker image using:

```docker build -f docker/Dockerfile -t standard_product .```

See the testing section for more details on how to test and interact with the code.

## Reference for TopsApp

TopsApp takes in SLC data from Sentinel-1 and runs the [TopsApp](https://github.com/isce-framework/isce2-docs/blob/master/Notebooks/UNAVCO_2020/TOPS/topsApp.ipynb) from ISCE2 automatically. See the linked notebook for a description of the algorithm and how to use this ISCE2 processing outside of the PGE.

## Testing Setup

Use the end-to-end tests expounded in the `tests` directory. Please see the [tests/readme.md](tests/readme.md) for more details.

**Warning**: *each end-to-end test directory can take anywhere from 30 GB (for restricted areas of interest) to 130 GB (for those run on the full area).*

**Warning**: *permissions of a mounted volume within a docker container may change the permissions of local files. I ignore permission changes for git tracking per this [thread](https://stackoverflow.com/questions/1257592/how-do-i-remove-files-saying-old-mode-100755-new-mode-100644-from-unstaged-cha)*.

## Release History

### Coseismic

* v1.0.0
    * Reorganized Repo from [here](https://github.com/aria-jpl/ariamh/tree/ARIA-529/interferogram/sentinel)

### Standard-product

* v2.0.4
    * Reorganized Repo from [here](https://github.com/aria-jpl/ariamh/tree/ARIA-581/interferogram/sentinel)


## Contributing

1. Fork this repo
2. Create your feature branch (`git checkout -b feature/fooBar`)
3. Commit your changes (`git commit -am 'Add some fooBar'`)
4. Push to the branch (`git push origin feature/fooBar`)
5. Create a new Pull Request


## Support

Please put issues in `Issues` page in this repo so we can track needed feature requets.