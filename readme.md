# topsApp-pge

This repo represents the topsAPP Product Generation Executable (PGE) for the [TopsApp](https://github.com/isce-framework/isce2-docs/blob/master/Notebooks/UNAVCO_2020/TOPS/topsApp.ipynb) portion of the standard product pipeline generating interferograms from Sentinel-1.


## Installation

The best way to run this is to build a docker container via `docker build -f docker/Dockerfile -t standard_product`. There is a different repo expounding how this is done. Some initial setup is required to test this because it requires a lot of input data (approximately 15 GB) and can produce output products totally 130 GB.

## Reference for TopsApp

Takes in SLC data and runs the [TopsApp](https://github.com/isce-framework/isce2-docs/blob/master/Notebooks/UNAVCO_2020/TOPS/topsApp.ipynb) from ISCE2 automatically.

## Testing Setup

See the `readme.md` in tests. It takes a bit of setup which we summarize:

1. Download (large slc files)
2. Build and name docker image
3. Obtain config files necessary for local run
4. Use docker compose files to run tests on various datasets and pipeline

Once this is setup, a simple `tests/test_all.sh` can be run.

## Release History

* 0.0.1
    * Reorganized Repo from [here](https://github.com/aria-jpl/ariamh/tree/ARIA-529/interferogram/sentinel)


## Contributing

1. Fork it (<https://github.com/yourname/yourproject/fork>)
2. Create your feature branch (`git checkout -b feature/fooBar`)
3. Commit your changes (`git commit -am 'Add some fooBar'`)
4. Push to the branch (`git push origin feature/fooBar`)
5. Create a new Pull Request


## Support

To be filled out