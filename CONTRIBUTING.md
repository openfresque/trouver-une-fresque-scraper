# Contributing

Before contributing to this project, please make sure that your git config is correct:

```console
git config --global user.name "John Doe"
git config --global user.email johndoe@example.com
```

Follow the installation instructions [here](https://pre-commit.com/#install) to install `pre-commit` hooks. Then, execute the `pre-commit install` command to install the Black code formatter.

```console
pre-commit install
pre-commit run --all-files
```

If you change scraping logic, make sure to run the `compare.py` utility to visualize the number of records scraped without and with your proposed modification.

```console
python compare.py results/events_20240125_194439.json results/events_20240130_121930.json
```
