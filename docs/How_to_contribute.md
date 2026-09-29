---
layout: default
title: How to contribute
nav_order: 6
---

# Contributing
## Reporting a bug or requesting a feature
If you have encountered a bug or would like to request or propose a new feature, please feel free to create a new issue using the appropriate template.

## Implementing a requested feature or fixing a known bug
If you want to fix a known bug or implement a new feature, please first create a fork of the repository.
After you have implemented your changes, you can propose them for inclusion in the project by creating a pull request from your fork into the `master` branch.
Please link the issue of the implemented feature or the fixed bug in the pull request for clearness, or add the respective [keywords](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue#linking-a-pull-request-to-an-issue-using-a-keyword#linking-a-pull-request-to-an-issue-using-a-keyword).

# Contributing as a project member
## Reporting a bug or requesting a feature
The process is identical to the previously mentioned process for contributors which are not part of the project.

## Solving an issue
The process to solve an already known issue (bug or feature request) is basically identical to the previously described process.
However, instead of creating a fork of the repository please create a branch with a descriptive name, which allows to understand it's purpose and it's relation to the targeted issue.
A good and easy option for this is to use the `Create a branch` link which can be found in the `Development` section of each issue.
Follow the instructions for determining the Version number depending on the contents of your branch and create a pull request to the respective release branch.

## Setup for developers
In general it is sufficient to follow the general installation instructions. However the following tips can help you to be more productive:
 - Work on python code in a virtual environment
 - Install the python programs in development mode by executing `pip install -e .[dev]` from the project main directory
   - The `-e` switch ensures that changes in the python source code are immediately active.
   - `[dev]` also installs some development requirements (e.g. mypy, black, pre-commit).
 - Install some git hooks by running `pre-commit install` from the main directory of this project. These hooks help to ensure a good quality of the commited code by automatically running some checks:
   - black is run to **format** python source code
   - python **type safety** is improved with mypy
   - we enforce [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/)
   - other checks like looking for unneccesary whitespace and preventing large files to be added


## Commit messages
Commit messages should follow the conventional commits format: [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/)

## Creating a new release
Execute the following steps in order to create a new DiscoPoP release:
- Switch to the release branch (e.g. `release/1.2.3`) which shall be released
- Update the version file in the repository (`discopop_library/global_data/version/VERSION`)
- Create a `.deb` package by executing `scripts/dev/create_package.sh`. The package will be created in `packages`.
- Create a pull request to the `master` branch and validate the changes
- Merge the pull request by rebasing and create a tag on the `master` branch with the name `v1.2.3`
    - Creating the tag triggers the automatic publication of the project to PyPi
    - Creating the tag triggers the automatic creation of a release draft
- Update the newly created release draft
  - Release tag: `v1.2.3`
  - Release title: `DiscoPoP Version 1.2.3`
  - Description should contain a summary of the most relevant changes
  - Add the created `.deb` package to the list of files
- If everything is fine, publish the new release

### Determining the Version Number
Lets assume a current version number `1.2.3`.
A new version number shall be determined as follows:
* Release only contains Bugfixes and minor improvements (e.g. code cleanup, stability fixes etc.) or documentation updates.
    * ==> Increase the last digit by `1`
* Release adds / modifies features with only a relatively minor impact (e.g. adding a new flag), <b>while ensuring full compatibility</b> with the previous version.
    * ==> Increase middle digit by `1`.
    * ==> Set last digit to `0`.
* Release adds a major new feature or modifies any interface (for example by modifying the format of input or output data) in such a way that it is <b>not fully compatible</b> with the previous version anymore.
    * ==> Increase first digit by `1`.
    * ==> Set remaining digits to `0`.

### Publish to PyPi
To publish a package update to PyPi, crate and upload a tag on the respective branch.
To trigger an update of:
- the profiler, use `profiler_v*`
- the explorer, use `explorer_v*`
- the library, use `library_v*`
as tag names, where `*` can be a version number as described above, but also be formatted as follows to publish alpha or beta packages.
To publish package 1.2.3 alpha version 4, use `1.2.3a4` as version string. For a beta release use `b` instead.
Update the `VERSION` file of the respective package accordingly.

# Developer hints
## Output folder structure
All tools developed as part of the DiscoPop Project make use of the following folder structure:
```
- project root/
 - .discopop/
  - FileMapping.txt
  - <tool_1>/
    - tool_1 output files
    - private/
     - tool_1 intermediate files
  - <tool_2>/
    - ...
  - ...
```
, where no data should be stored / created outside the `.discopop` folder in order to keep the users build directory as clean as possible.
Files which are read by different tools, e.g. the `FileMapping.txt`, shall be stored in the `.discopop` folder.
Each tool may create a folder. In case data from these files is required by another tool, think about how to encode the information in a easy-to-use and structured format, preferrably JSON. If possible, please do not rely on exporting to simple `.txt` files as parsing adds a potential point of failure.
Output data for use by other tools should be stored in the folder of the creating tool. Intermediate files may be stored in a folder named `private` and shall not be used by other tools.
Analysis tools, like pattern detection scripts etc. shall be structured in such a way, that a execution from within the `.discopop` folder is intended.
